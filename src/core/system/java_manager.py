"""
Java 管理器

提供 Java 版本偵測、快取管理、winget 安裝引導等核心功能。
從 src/utils/java_support/ 遷移而來，合併 java_utils.py 與 java_downloader.py。
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import threading
from pathlib import Path
from typing import ClassVar, Protocol

from ...utils import HTTPUtils, PathUtils, RuntimePaths, SubprocessUtils, get_logger, get_shared_manager
from .. import MinecraftVersionManager

logger = get_logger().bind(component="JavaManager")


class JavaInstallInteraction(Protocol):
    """Java 自動安裝流程需要的使用者互動介面。"""

    @staticmethod
    def ask_yes_no_cancel(title: str, message: str, **kwargs) -> bool | None:
        """
        詢問使用者是否同意動作。

        Args:
            title: 對話框標題。
            message: 對話框訊息。
            **kwargs: UI adapter 選項。

        Returns:
            使用者選擇；取消或無法判斷時回傳 None。
        """

    @staticmethod
    def show_info(title: str, message: str, **kwargs) -> None:
        """
        顯示資訊訊息。

        Args:
            title: 訊息標題。
            message: 訊息內容。
            **kwargs: UI adapter 選項。
        """

    @staticmethod
    def show_error(title: str, message: str, **kwargs) -> None:
        """
        顯示錯誤訊息。

        Args:
            title: 訊息標題。
            message: 訊息內容。
            **kwargs: UI adapter 選項。
        """


class JavaManager:
    """提供 Java 偵測、快取與安裝流程的統一管理。"""

    COMMON_JAVA_PATHS: ClassVar[list[str]] = [
        "C:\\Program Files\\Java",
        "C:\\Program Files (x86)\\Java",
        "C:\\Program Files\\Microsoft",
    ]
    ENV_VARS: ClassVar[list[str]] = ["JAVA_HOME"]
    JAVA_CACHE_FILE_NAME: ClassVar[str] = "java_candidates_cache.json"
    _java_cache_lock: ClassVar[threading.Lock] = threading.Lock()
    _cached_java_candidates: ClassVar[list[tuple[str, int]] | None] = None

    # ── Java 版本偵測 ──────────────────────────────────────────

    @staticmethod
    def get_java_version(java_path: str) -> int | None:
        """
        取得指定 `javaw.exe` 的主要版本號。

        Args:
            java_path: `javaw.exe` 的完整路徑。

        Returns:
            Java major 版本，找不到或解析失敗時回傳 None。
        """
        try:
            res = SubprocessUtils.run_checked(
                [java_path, "-version"],
                stdin=SubprocessUtils.DEVNULL,
                stdout=SubprocessUtils.PIPE,
                text=True,
                stderr=SubprocessUtils.STDOUT,
                check=True,
            )
            out = res.stdout or ""
            m = re.search('version "(\\d+)\\.(\\d+)', out)
            if m:
                major = int(m.group(1))
                if major == 1:
                    return int(m.group(2))
                return major
            m = re.search('version "(\\d+)"', out)
            if m:
                return int(m.group(1))
        except Exception as e:
            logger.exception(f"取得 Java 版本失敗 {java_path}: {e}")
        return None

    # ── 快取管理 ──────────────────────────────

    @staticmethod
    def _get_java_cache_path() -> Path:
        return RuntimePaths.ensure_dir(RuntimePaths.get_cache_dir()) / JavaManager.JAVA_CACHE_FILE_NAME

    @staticmethod
    def _load_java_candidates_from_cache() -> list[tuple[str, int]] | None:
        cache_path = JavaManager._get_java_cache_path()
        cache_data = PathUtils.load_json(cache_path)
        if not isinstance(cache_data, dict):
            return None
        candidates: list[tuple[str, int]] = []
        cached_items = cache_data.get("candidates", [])
        if not isinstance(cached_items, list):
            return None
        for item in cached_items:
            if not isinstance(item, dict):
                continue
            candidate_path = item.get("path")
            candidate_major = item.get("major")
            if not isinstance(candidate_path, str) or not isinstance(candidate_major, int):
                continue
            javaw_exe = Path(str(candidate_path))
            if not javaw_exe.is_file():
                continue
            try:
                candidates.append((str(javaw_exe.resolve()), candidate_major))
            except OSError:
                continue
        if not candidates:
            return None
        return candidates

    @staticmethod
    def _resolve_java_candidate(javaw_exe: Path) -> tuple[str, int] | None:
        major = JavaManager.get_java_version(str(javaw_exe))
        if not major:
            return None
        try:
            resolved_javaw_exe = javaw_exe.resolve()
            return str(resolved_javaw_exe), major
        except OSError:
            return str(javaw_exe), major

    @staticmethod
    def _scan_and_cache_local_java_candidates() -> list[tuple[str, int]]:
        search_paths = set()
        for base_str in JavaManager.COMMON_JAVA_PATHS:
            base = Path(base_str)
            if base.exists():
                for subdir in base.iterdir():
                    if subdir.is_dir():
                        search_paths.add(str(subdir / "bin"))
        for var in JavaManager.ENV_VARS:
            val = os.environ.get(var)
            if val:
                for p in val.split(";"):
                    java_bin = Path(p) / "bin"
                    search_paths.add(str(java_bin))
        candidates: list[tuple[str, int]] = []
        candidate_paths: set[Path] = set()
        try:
            where_path = PathUtils.find_executable("where")
            if where_path:
                result = SubprocessUtils.run_checked(
                    [where_path, "javaw"], stdin=SubprocessUtils.DEVNULL, capture_output=True, text=True, check=False
                )
                if result.returncode == 0:
                    for java_path_str in (result.stdout or "").strip().splitlines():
                        java_path_obj = Path(java_path_str)
                        if java_path_obj.name.lower() == "javaw.exe":
                            candidate_paths.add(java_path_obj)
        except Exception as e:
            logger.exception(f"搜尋 Java 失敗: {e}")
        for p_str in search_paths:
            search_path_obj = Path(p_str).resolve()
            javaw_exe = search_path_obj / "javaw.exe"
            if javaw_exe.exists():
                candidate_paths.add(javaw_exe)
        if not candidate_paths:
            return candidates
        futures = [
            get_shared_manager().run(JavaManager._resolve_java_candidate, javaw_exe)
            for javaw_exe in sorted(candidate_paths)
        ]
        for future in futures:
            resolved_candidate = future.result()
            if resolved_candidate:
                candidates.append(resolved_candidate)
        seen = set()
        final_results = []
        for c_path, c_major in candidates:
            if (c_path, c_major) not in seen:
                seen.add((c_path, c_major))
                final_results.append((c_path, c_major))
        final_results.sort(key=lambda x: x[1])
        cache_path = JavaManager._get_java_cache_path()
        if final_results:
            cached_items: list[dict[str, object]] = []
            for java_path_str, major in final_results:
                cached_items.append({"path": java_path_str, "major": major})
            PathUtils.save_json_if_changed(cache_path, {"candidates": cached_items})
        else:
            with contextlib.suppress(OSError):
                if cache_path.exists():
                    cache_path.unlink()
        return final_results

    @staticmethod
    def refresh_java_candidates_cache() -> list[tuple[str, int]]:
        """
        重新掃描本機 Java 並更新 JSON 快取。

        Returns:
            最新掃描到的 Java 候選清單。
        """
        final_results = JavaManager._scan_and_cache_local_java_candidates()
        with JavaManager._java_cache_lock:
            JavaManager._cached_java_candidates = list(final_results)
        return final_results

    @staticmethod
    def get_all_local_java_candidates() -> list:
        """
        取得所有可用的 `javaw.exe` 路徑及其主要版本號列表。

        Returns:
            `javaw.exe` 路徑與 major 版本的配對清單。
        """
        with JavaManager._java_cache_lock:
            if JavaManager._cached_java_candidates:
                return list(JavaManager._cached_java_candidates)

        cached_candidates = JavaManager._load_java_candidates_from_cache()
        if cached_candidates:
            with JavaManager._java_cache_lock:
                JavaManager._cached_java_candidates = list(cached_candidates)
            logger.debug(f"使用快取的 Java 偵測結果：{len(cached_candidates)} 筆")
            return cached_candidates

        final_results = JavaManager._scan_and_cache_local_java_candidates()
        if final_results:
            with JavaManager._java_cache_lock:
                JavaManager._cached_java_candidates = list(final_results)
        logger.debug(f"找到 {len(final_results)} 個 Java 執行檔選擇：")
        for r_path, r_major in final_results:
            logger.debug(f"  {r_path} -> {r_major}")
        return final_results

    # ── Minecraft 版本對應 Java 版本 ─────────────────

    @staticmethod
    def _ensure_cache_exists(cache_path: Path):
        """確保快取檔案存在且非空"""
        if not cache_path.exists() or cache_path.stat().st_size == 0:
            try:
                vm = MinecraftVersionManager()
                vm.fetch_versions()
            except Exception as e:
                raise FileNotFoundError(f"找不到 {cache_path}，且自動建立快取失敗: {e}") from e
            if not cache_path.exists() or cache_path.stat().st_size == 0:
                raise FileNotFoundError(f"找不到 {cache_path} 或檔案為空")

    @staticmethod
    def get_required_java_major(mc_version: str) -> int:
        """
        根據 Minecraft 版本決定所需 Java major 版本。

        Args:
            mc_version: Minecraft 版本字串。

        Returns:
            對應的 Java major 版本。
        """
        if not isinstance(mc_version, str) or not mc_version:
            raise ValueError("mc_version 必須為非空字串")
        cache_path = RuntimePaths.get_cache_dir() / "mc_versions_cache.json"
        JavaManager._ensure_cache_exists(cache_path)
        data = PathUtils.load_json(cache_path)
        if data is None:
            raise ValueError(f"無法解析 {cache_path} 內容")
        if isinstance(data, dict):
            data = [data]
        for v in data:
            if v.get("id") == mc_version and "url" in v:
                url = v["url"]
                ver_json = HTTPUtils.get_json(url, timeout=8)
                if ver_json:
                    java_info = ver_json.get("javaVersion")
                    if java_info and "majorVersion" in java_info:
                        return int(java_info["majorVersion"])
                    java_info2 = ver_json.get("java_version")
                    if java_info2 and "major" in java_info2:
                        return int(java_info2["major"])
                    json_str = PathUtils.to_json_str(ver_json)
                    m = re.search(r'"major(?:Version)?"\s*:\s*(\d+)', json_str)
                    if m:
                        return int(m.group(1))
                raise ValueError(f"找不到 majorVersion，url: {url}")
        raise ValueError(f"找不到對應 mc_version: {mc_version}")

    # ── 最佳 Java 路徑選擇 ──────────────────────

    @staticmethod
    def get_best_java_path(
        mc_version: str,
        required_major: int | None = None,
        ask_download: bool = True,
        interaction: JavaInstallInteraction | None = None,
    ) -> str | None:
        """
        為指定 Minecraft 版本選擇最合適的 `javaw.exe` 路徑。

        Args:
            mc_version: Minecraft 版本字串。
            required_major: 指定的 Java major 版本；未提供時會自動推導。
            ask_download: 找不到符合版本時是否詢問自動安裝。
            interaction: UI 層注入的互動介面；未提供時不會在工具層直接顯示對話框。

        Returns:
            找到時回傳 `javaw.exe` 路徑，否則回傳 None。
        """
        required_major = required_major if required_major else JavaManager.get_required_java_major(mc_version)
        candidates = JavaManager.get_all_local_java_candidates()
        for path, major in candidates:
            if major == required_major:
                return path
        if ask_download and interaction is None:
            logger.info(f"找不到 Java {required_major}，但工具層未提供互動介面，因此不執行自動安裝提示。")
            return None
        if ask_download and interaction is not None:
            vendor = "Oracle jre" if required_major == 8 else "Microsoft JDK"
            res = interaction.ask_yes_no_cancel(
                "Java 未找到",
                (
                    f"未找到合適的 Java {required_major}。是否由程式自動安裝 {vendor}？\n\n"
                    "選擇 [是] 會在背景使用 winget 安裝並自動同意相關授權條款；\n"
                    "選擇 [否] 則不會安裝，由你自行下載並在程式中指定 Java 路徑。"
                ),
                show_cancel=False,
            )
            if res:
                try:
                    JavaManager._install_java_with_winget(required_major)
                    JavaManager.refresh_java_candidates_cache()
                    candidates = JavaManager.get_all_local_java_candidates()
                    for path, major in candidates:
                        if major == required_major:
                            interaction.show_info(
                                title=f"Java {required_major} 安裝成功",
                                message=f"Java {required_major} 已成功安裝並偵測到 javaw.exe。",
                            )
                            return path
                except Exception as e:
                    logger.exception(f"自動下載 Microsoft JDK {required_major} 失敗：{e}")
                    interaction.show_error(
                        "Java 下載失敗",
                        f"自動下載 Microsoft JDK {required_major} 失敗：{e}\n請手動安裝或指定 Java 路徑。",
                    )
            else:
                interaction.show_info(
                    "請手動下載 Java",
                    f"請手動安裝或指定 Java 路徑。\n建議安裝 Microsoft JDK、Adoptium、Azul、Oracle JDK {required_major} 等。",
                )
        return None

    # ── winget 安裝支援 ──────────────────────────

    @staticmethod
    def _get_winget_path() -> Path | None:
        """
        尋找 winget 的執行路徑。
        優先檢查環境變數 PATH，若找不到則手動推算 Windows App Alias 路徑。
        """
        winget_str = shutil.which("winget")
        if winget_str:
            return Path(winget_str)

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            alias_path = Path(local_app_data).resolve() / "Microsoft" / "WindowsApps" / "winget.exe"
            if alias_path.exists():
                return alias_path

        return None

    @staticmethod
    def _is_winget_available() -> bool:
        """
        確認 winget 是否可用，並詳細記錄失敗原因以利 Debug。
        """
        winget_path = JavaManager._get_winget_path()

        if not winget_path:
            logger.error("在系統 PATH 或預設 App 執行別名路徑中皆找不到 winget.exe")
            return False

        try:
            process = SubprocessUtils.run_checked(
                [str(winget_path), "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
                stdin=SubprocessUtils.DEVNULL,
                creationflags=SubprocessUtils.CREATE_NO_WINDOW,
            )
            logger.info(f"偵測到 winget，路徑: {winget_path}, 版本: {process.stdout.strip()}")
            return True

        except FileNotFoundError:
            logger.error(f"執行失敗：找不到檔案 {winget_path}，可能權限不足或別名失效。")
            return False
        except SubprocessUtils.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "無錯誤輸出 (stderr)"
            logger.error(f"winget 存在但回傳錯誤代碼 ({e.returncode})。錯誤內容: {error_msg}")
            return False
        except Exception as e:
            logger.exception(f"檢查 winget 時發生未預期的異常: {e}")
            return False

    @staticmethod
    def _install_java_with_winget(major: int):
        """
        透過 winget 安裝指定主版本的 Java。

        Args:
            major: Java 主要版本號。
        """

        if not JavaManager._is_winget_available():
            raise Exception(
                "無法調用 winget 工具。這可能是因為：\n"
                "1. 系統未安裝「應用程式安裝員 (App Installer)」。\n"
                "2. 您的 Windows 版本過舊。\n"
                "3. 環境變數中缺少 %LocalAppData%\\Microsoft\\WindowsApps。\n"
                "請檢查程式日誌以獲取詳細錯誤代碼。"
            )

        if major == 8:
            pkg = "Oracle.JavaRuntimeEnvironment"
        elif major in (11, 16, 17, 21, 25):
            pkg = f"Microsoft.OpenJDK.{major}"
        else:
            raise Exception(f"不支援自動安裝 Java 主要版本 {major}，請手動前往官網下載。")

        winget_cmd = ["winget", "install", "--accept-package-agreements", "--accept-source-agreements", pkg]

        try:
            logger.info(f"正在執行安裝指令: {' '.join(winget_cmd)}")
            SubprocessUtils.run_checked(
                winget_cmd,
                check=True,
                stdin=SubprocessUtils.DEVNULL,
            )
            logger.info(f"Java {major} ({pkg}) 安裝程序已完成。")
        except Exception as e:
            logger.exception(f"winget 安裝過程發生異常: {e}")
            raise Exception(f"透過 winget 安裝 {pkg} 失敗。建議手動開啟終端機執行：\nwinget install {pkg}") from e
