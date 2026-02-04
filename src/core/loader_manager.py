#!/usr/bin/env python3
"""
模組載入器管理器
負責處理 Fabric、Forge 載入器的版本管理與下載
支援自動取得最新版本資訊並提供相容性檢查
Loader Manager Module
Responsible for managing and downloading versions of Fabric and Forge loaders with automatic version retrieval and compatibility checks
"""

import re
import subprocess as _subprocess
from subprocess import PIPE, STDOUT

CREATE_NO_WINDOW = getattr(_subprocess, "CREATE_NO_WINDOW", 0)
from contextlib import suppress
from pathlib import Path

from defusedxml import ElementTree as ET

from src.models import LoaderVersion
from src.utils import (
    HTTPUtils,
    PathUtils,
    ServerDetectionUtils,
    Singleton,
    UIUtils,
    ensure_dir,
    get_best_java_path,
    get_cache_dir,
    get_logger,
    popen_checked,
)

from .version_manager import MinecraftVersionManager

logger = get_logger().bind(component="LoaderManager")


class LoaderManager(Singleton):
    """
    模組載入器管理器類別，管理 Fabric 和 Forge 載入器版本
    Loader Manager class for managing Fabric and Forge loader versions
    """

    # ====== 初始化與快取管理 ======
    _initialized: bool = False

    # 初始化載入器管理器
    def __init__(self):
        """
        初始化載入器管理器
        Initialize loader manager
        """
        # 避免重複初始化
        if self._initialized:
            return
        cache_dir = ensure_dir(get_cache_dir())
        self.fabric_cache_file = str(cache_dir / "fabric_versions_cache.json")
        self.forge_cache_file = str(cache_dir / "forge_versions_cache.json")
        # 添加記憶體快取以避免重複讀取檔案
        self._version_cache = {}
        self._initialized = True

    def clear_cache_file(self):
        """
        通用快取檔案清除方法（同時清除記憶體快取）。
        Generic cache file clearing method.

        Args:
            None

        Returns:
            None
        """
        try:
            fabric_path = Path(self.fabric_cache_file)
            forge_path = Path(self.forge_cache_file)

            fabric_path.unlink(missing_ok=True)
            forge_path.unlink(missing_ok=True)

            # 清除記憶體快取
            self._version_cache.clear()
        except PermissionError as e:
            logger.exception(f"清除快取檔案失敗: {e}")
            UIUtils.show_error(
                "清除快取檔案失敗",
                f"無法刪除快取檔案\n權限不足\n{e}",
                topmost=True,
            )
        except Exception as e:
            logger.exception(f"清除快取檔案失敗: {e}")
            UIUtils.show_error("清除快取檔案失敗", f"無法刪除快取檔案\n{e}", topmost=True)

    # ======== 公開 API ========
    def download_server_jar_with_progress(
        self,
        loader_type: str,
        minecraft_version: str,
        loader_version: str,
        download_path: str,
        progress_callback=None,
        cancel_flag: dict | None = None,
        user_java_path: str | None = None,
        parent_window=None,
    ) -> bool | str:
        """
        依 loader_type 下載並部署伺服器檔案。
        Vanila/Fabric → bool；Forge → 成功時回傳主 JAR 相對路徑字串。
        Download and deploy server files based on loader_type.
        Vanilla/Fabric → bool; Forge → returns main JAR relative path string on success.

        Args:
            loader_type (str): 載入器類型
            minecraft_version (str): Minecraft 版本
            loader_version (str): 載入器版本
            download_path (str): 下載路徑
            progress_callback (Callable[[int] | None]): 進度回調函數
            cancel_flag (dict | None): 取消標誌
            user_java_path (str | None): 使用者指定的 Java 路徑
            parent_window (tk.Toplevel | None): 父視窗

        Returns:
            bool | str: 下載結果
        """
        lt = self._standardize_loader_type(loader_type, loader_version)

        # 1. 取得 Java 執行檔路徑（先找，找不到就自動安裝再找一次）
        if user_java_path and Path(user_java_path).exists():
            java_path = user_java_path
        else:
            java_path = get_best_java_path(minecraft_version)
        if not java_path:
            return False

        # 2. 依不同載入器執行
        if lt == "vanilla":
            return self._download_vanilla_server(minecraft_version, download_path, progress_callback, cancel_flag)

        if lt == "fabric":
            return self._download_and_run_installer(
                installer_url="https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.1/fabric-installer-1.1.1.jar",
                installer_args=[
                    java_path,
                    "-jar",
                    "{installer}",
                    "server",
                    "-mcversion",
                    minecraft_version,
                    "-loader",
                    loader_version,
                    "-dir",
                    str(Path(download_path).parent),
                ],
                minecraft_version=minecraft_version,
                _loader_version=loader_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                need_vanilla=True,
                parent_window=parent_window,
            )

        if lt == "forge":
            installer_url = (
                "https://maven.minecraftforge.net/net/minecraftforge/forge/"
                f"{minecraft_version}-{loader_version}/"
                f"forge-{minecraft_version}-{loader_version}-installer.jar"
            )
            return self._download_and_run_installer(
                installer_url=installer_url,
                installer_args=[
                    java_path,
                    "-jar",
                    "{installer}",
                    "--installServer",
                ],
                minecraft_version=minecraft_version,
                _loader_version=loader_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                need_vanilla=False,
                parent_window=parent_window,
            )

        return self._fail(
            progress_callback,
            f"未知的載入器類型: {loader_type}",
            debug=f"[DEBUG] Unknown loader_type={loader_type}",
        )

    def preload_loader_versions(self):
        """
        從 API 取得所有載入器版本並覆蓋寫入 json。
        get all loader versions from API and overwrite json.

        Args:
            parent (tk.Toplevel | None): 父視窗

        Returns:
            None
        """
        self._preload_fabric_versions()
        self._preload_forge_versions()

    def _preload_fabric_versions(self):
        logger.debug("預先抓取 Fabric 載入器版本...", "LoaderManager")
        fabric_url = "https://meta.fabricmc.net/v2/versions/loader"
        try:
            data = HTTPUtils.get_json(fabric_url, timeout=15)
            if data:
                # 只保留 stable 版本（正式版）
                stable_versions = [v for v in data if v.get("stable", False)]
                logger.debug(f"Fabric 版本過濾: {len(data)} -> {len(stable_versions)} (只保留 stable)")

                # 比較現有快取，減少磁碟寫入
                write_needed = True
                fabric_path = Path(self.fabric_cache_file)
                existing = PathUtils.load_json(fabric_path)
                if existing == stable_versions:
                    write_needed = False

                if write_needed:
                    PathUtils.save_json(fabric_path, stable_versions)
        except Exception as e:
            logger.exception(f"載入 Fabric 版本失敗: {e}")
            UIUtils.show_error(
                "載入 Fabric 版本失敗",
                f"無法從 API 獲取 Fabric 版本：{e}",
                topmost=True,
            )

    def _preload_forge_versions(self) -> None:
        logger.debug("預先抓取  Forge 載入器版本...", "LoaderManager")
        try:
            forge_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
            content = HTTPUtils.get_content(forge_url, timeout=15)

            if content:
                logger.debug("成功獲取 Forge XML 數據", "LoaderManager")
                root = ET.fromstring(content)
                versions = []

                # 提取所有版本
                for version_elem in root.findall(".//version"):
                    version_text = version_elem.text
                    if version_text and "-" in version_text:
                        # 篩除測試版本：pre, prerelease, beta, alpha, snapshot, rc
                        lower_text = version_text.lower()
                        test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                        if any(keyword in lower_text for keyword in test_keywords):
                            continue
                        versions.append(version_text.strip())

                logger.debug(f"Forge 版本過濾後: {len(versions)} 個穩定版本")

                # 處理版本號，移除非數字與點號的字元
                filtered_versions = []
                for v in versions:
                    parts = v.split("-", 1)
                    if len(parts) == 2:
                        mc_ver = re.sub(r"[^0-9.]", "", parts[0])
                        forge_ver = re.sub(r"[^0-9.]", "", parts[1])
                        if mc_ver and forge_ver:
                            filtered_versions.append(f"{mc_ver}-{forge_ver}")

                if len(filtered_versions) > 0:
                    # 按 Minecraft 版本分組
                    version_dict: dict[str, list[str]] = {}
                    for version in filtered_versions:
                        if "-" in version:
                            try:
                                parts = version.split("-", 1)
                                if len(parts) == 2:
                                    mc_version = parts[0]
                                    if mc_version not in version_dict:
                                        version_dict[mc_version] = []
                                    version_dict[mc_version].append(version)
                            except Exception as e:
                                logger.debug(
                                    f"解析 Forge 版本字串失敗 '{version}': {e}",
                                    "LoaderManager",
                                )
                                continue

                    # 對每個 MC 版本的 Forge 版本進行排序（最新在前）
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(reverse=True)
                        # 限制每個版本最多10個 Forge 版本，避免數據過多
                        version_dict[mc_version] = version_dict[mc_version][:10]

                    # 比較現有快取，減少磁碟寫入
                    write_needed = True
                    forge_path = Path(self.forge_cache_file)
                    existing = PathUtils.load_json(forge_path)
                    if existing == version_dict:
                        write_needed = False

                    if write_needed:
                        # 寫入快取檔案
                        PathUtils.save_json(forge_path, version_dict)
                    return
            return

        except Exception as e:
            logger.exception(f"Maven metadata API 方法失敗: {e}")
            UIUtils.show_error(
                "載入 Forge 版本失敗",
                f"無法從 Maven metadata API 獲取 Forge 版本：{e}",
                topmost=True,
            )
            return

    def get_compatible_loader_versions(self, mc_version: str, loader_type: str) -> list[LoaderVersion]:
        """
        只從 json 快取檔案取得相容的載入器版本列表（使用記憶體快取優化）。
        get all compatible loader versions from cache (with memory caching optimization).

        Args:
            mc_version (str): 要檢查的 MC 版本字串
            loader_type (str): 載入器類型（"fabric" 或 "forge"）

        Returns:
            List[LoaderVersion]: 相容的 Fabric 載入器版本列表
        """
        # 建立快取鍵
        cache_key = f"{loader_type.lower()}_{mc_version}"

        # 檢查記憶體快取
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]

        # 檢查快取檔案是否存在
        if not Path(self.fabric_cache_file).exists() and not Path(self.forge_cache_file).exists():
            return []
        # Fabric
        if loader_type.lower() == "fabric":
            try:
                # 檢查 MC 版本是否與 Fabric 兼容（1.14+）
                if not ServerDetectionUtils.is_fabric_compatible_version(mc_version):
                    # 不快取空結果，因為相容性可能在未來改變
                    return []

                cache = PathUtils.load_json(Path(self.fabric_cache_file))
                if not cache:
                    return []

                result = []
                # 返回與兼容的MC版本相對應的Fabric加載器版本
                for item in cache:
                    if isinstance(item, dict) and "version" in item:
                        ver = item["version"]
                        if ver:
                            result.append(LoaderVersion(version=ver))

                # 只快取非空結果
                if result:
                    self._version_cache[cache_key] = result
                return result
            except Exception as e:
                logger.exception(f"獲取 Fabric 版本時發生錯誤: {e}")
                return []
        # Forge
        elif loader_type.lower() == "forge":
            try:
                cache = PathUtils.load_json(Path(self.forge_cache_file))
                if not cache:
                    return []

                result = []

                # 檢查格式（完整版本 API）: { "1.21.4": ["1.21.4-54.0.0", "1.21.4-54.0.1", ...] }
                if mc_version in cache and isinstance(cache[mc_version], list):
                    for version in cache[mc_version]:
                        # 提取 Forge 版本號（去掉 MC 版本前綴）
                        if "-" in version and version.startswith(mc_version):
                            forge_version = version.split("-", 1)[1]
                            result.append(LoaderVersion(version=forge_version))

                # 只快取非空結果
                if result:
                    self._version_cache[cache_key] = result
                return result
            except Exception as e:
                logger.exception(f"獲取 Forge 版本時發生錯誤: {e}")
                return []
        return []

    # ---------------------- 私有輔助方法 ----------------------
    # === 下載 × 執行安裝器 ===
    def _download_and_run_installer(
        self,
        installer_url: str,
        installer_args: list[str],
        minecraft_version: str,
        _loader_version: str,
        download_path: str,
        progress_callback,
        cancel_flag,
        need_vanilla: bool = False,
        parent_window=None,
    ) -> bool | str:
        """Fabric 與 Forge 共用：下載安裝器 → （可選）先下載 vanilla → 執行安裝器。

        Arg:
            self: LoaderManager 實例。
            installer_url (str): 安裝器的下載 URL。
            installer_args (List[str]): 安裝器的啟動參數。
            minecraft_version (str): Minecraft 版本。
            loader_version (str): 載入器版本。
            download_path (str): 下載路徑。
            progress_callback: 進度回調函數。
            cancel_flag: 取消標誌。
            need_vanilla (bool): 是否需要下載 vanilla 伺服器。
            parent_window: 父視窗，用於顯示錯誤對話框。
        Returns:
            bool | str: 成功時返回 True，失敗時返回錯誤訊息。
        """
        installer_path = str(Path(download_path).parent / Path(installer_url).name)

        # 設定進度範圍
        if need_vanilla:
            # Fabric: 安裝器下載 (10-15%) -> Vanilla 下載 (15-90%) -> 安裝 (90-100%)
            dl_start, dl_end = 10, 15
            vanilla_start, vanilla_end = 15, 90
            install_start = 90
        else:
            # Forge: 安裝器下載 (10-25%) -> 安裝 (25-100%, 含函式庫下載)
            dl_start, dl_end = 10, 25
            vanilla_start, vanilla_end = 0, 0  # 不使用
            install_start = 25

        # 下載安裝器
        if not self._download_file_with_progress(
            installer_url,
            installer_path,
            progress_callback,
            dl_start,
            dl_end,
            "下載安裝器...",
            cancel_flag,
        ):
            return False

        # 需要 vanilla 伺服器？（Fabric）
        if need_vanilla and not self._download_vanilla_server(
            minecraft_version,
            download_path,
            lambda p, s: (
                progress_callback(vanilla_start + p * (vanilla_end - vanilla_start) / 100, s)
                if progress_callback
                else None
            ),
            cancel_flag,
        ):
            return False

        # 執行安裝器
        if progress_callback:
            progress_callback(install_start, "準備執行安裝器...")

        cmd = [arg if arg != "{installer}" else installer_path for arg in installer_args]
        # 確認命令參數為字串列表（避免不安全或意外類型）
        if not isinstance(cmd, list) or any(not isinstance(a, str) for a in cmd):
            logger.error(f"無效的安裝器命令參數: {cmd}")
            return self._fail(progress_callback, "執行安裝器失敗：無效的命令參數")

        # 使用 Popen 讀取輸出
        try:
            process = popen_checked(
                cmd,
                cwd=str(Path(download_path).parent),
                stdout=PIPE,
                stderr=STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )

            # 讀取輸出並更新進度
            if process.stdout is None:
                return False

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    line = line.strip()
                    if progress_callback and line:
                        if "Download" in line:
                            progress_callback(install_start, f"安裝中: {line[:40]}...")
                        elif "Processor" in line:
                            progress_callback(install_start, f"處理中: {line[:40]}...")

            if process.returncode != 0:
                logger.error(f"安裝器執行失敗 (Code {process.returncode})")
                return self._fail(
                    progress_callback,
                    f"安裝器執行失敗 (Code {process.returncode})",
                    debug=f"[DEBUG] cmd: {' '.join(cmd)}",
                )
        except Exception as e:
            logger.exception(f"執行安裝器時發生錯誤: {e}")
            return self._fail(
                progress_callback,
                f"執行安裝器時發生錯誤: {e}",
                debug=f"[DEBUG] Popen exception: {e}",
            )

        # Forge: 從 run.bat 抽取 java 指令行並完整寫入 start_server.bat
        try:
            base_dir = Path(download_path).parent
            run_bat_path = base_dir / "run.bat"
            run_sh_path = base_dir / "run.sh"
            start_server_path = base_dir / "start_server.bat"
            installer_log_path = base_dir / "installer.log"

            java_line = None

            # 1. 從 run.bat 擷取 java 指令行
            if run_bat_path.exists():
                try:
                    with run_bat_path.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if re.search(r"\bjava\s+@user_jvm_args\\.txt\b", line, re.IGNORECASE):
                                java_line = line.strip()
                                break
                    # 確保加上 nogui
                    if java_line and "nogui" not in java_line.lower():
                        java_line += " nogui"
                except Exception as e:
                    logger.warning(f"無法讀取 run.bat: {e}")
                    UIUtils.show_warning("讀取失敗", f"無法讀取 run.bat：{e}", parent=parent_window)

            # 2. 修改 start_server.bat 中以 java 開頭的指令行
            if java_line and start_server_path.exists():
                try:
                    with start_server_path.open("r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()

                    new_lines = []
                    replaced = False
                    for line in lines:
                        if not replaced and re.match(r"^\s*java\b", line, re.IGNORECASE):
                            new_lines.append(java_line + "\n")
                            replaced = True
                        else:
                            new_lines.append(line)

                    with start_server_path.open("w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                except Exception as e:
                    logger.exception(f"修改 start_server.bat 失敗: {e}")
                    UIUtils.show_warning(
                        "修改失敗",
                        f"無法修改 start_server.bat：{e}",
                        parent=parent_window,
                    )

            # 3. 清理 run.bat、run.sh、README.txt、installer、installer.log
            # 批量清理安裝過程產生的檔案
            try:
                for file_path in [
                    run_bat_path,
                    run_sh_path,
                    base_dir / "README.txt",
                    Path(installer_path),
                    installer_log_path,
                ]:
                    with suppress(FileNotFoundError):
                        file_path.unlink()
            except Exception as e:
                logger.exception(f"清理安裝檔失敗: {installer_path}: {e}")
                UIUtils.show_warning(
                    "清理失敗",
                    f"安裝完成，但無法清理安裝器檔案：{installer_path}\n可手動刪除。",
                    parent=parent_window,
                )

        except Exception as e:
            logger.exception(f"安裝過程中發生錯誤: {e}")
            UIUtils.show_error("安裝失敗", f"安裝過程中發生錯誤：{e}", parent=parent_window)

        return True

    # === Vanilla ===
    def _download_vanilla_server(
        self,
        minecraft_version: str,
        download_path: str,
        progress_callback,
        cancel_flag,
    ) -> bool:
        """下載 Minecraft Vanilla 伺服器 JAR 檔案。
        Download Minecraft Vanilla server JAR file.

        Args:
            minecraft_version: Minecraft 版本號
            download_path: 下載路徑
            progress_callback: 進度回調函數
            cancel_flag: 取消標誌
        Returns:
            是否成功

        """
        if progress_callback:
            progress_callback(10, "查詢 Minecraft 版本資訊...")

        # 優先使用 VersionManager 的快取查詢，失敗則回退到本地方法
        server_url = MinecraftVersionManager().get_server_download_url(
            minecraft_version,
        ) or self._get_minecraft_server_url(minecraft_version)

        if not server_url:
            return self._fail(progress_callback, "找不到 Minecraft 版本資訊")

        if progress_callback:
            progress_callback(20, "下載 Minecraft 伺服器...")

        return self._download_file_with_progress(
            server_url,
            download_path,
            progress_callback,
            20,
            100,
            "下載 Minecraft 伺服器...",
            cancel_flag,
        )

    # === 小工具 ===
    def _download_file_with_progress(
        self,
        url: str,
        dest_path: str,
        progress_callback,
        start_percent: int,
        end_percent: int,
        status_text: str,
        cancel_flag: dict | None,
    ) -> bool:
        """下載檔案並顯示進度。
        Download file and show progress.

        Args:
            url: 下載檔案的 URL
            dest_path: 下載後儲存的路徑
            progress_callback: 進度回調函數
            start_percent: 開始百分比
            end_percent: 結束百分比
            status_text: 狀態文字
            cancel_flag: 取消標誌

        Returns:
            是否成功

        """

        def on_progress(downloaded, total):
            if total > 0 and progress_callback:
                percent = start_percent + (downloaded / total) * (end_percent - start_percent)
                progress_callback(percent, status_text)

        def check_cancel():
            if cancel_flag and cancel_flag.get("cancelled"):
                if progress_callback:
                    self._fail(progress_callback, "已取消下載")
                return True
            return False

        if HTTPUtils.download_file(
            url,
            dest_path,
            progress_callback=on_progress,
            timeout=30,
            cancel_check=check_cancel,
        ):
            return True
        return self._fail(progress_callback, "下載失敗：無法獲取檔案")

    def _get_minecraft_server_url(self, mc_version: str) -> str | None:
        """根據 Minecraft 版本獲取伺服器 JAR 下載 URL。
        According to the Minecraft version, get the server JAR download URL.

        Args:
            mc_version: Minecraft 版本號

        Returns:
            伺服器 JAR 下載 URL

        """
        try:
            manifest = HTTPUtils.get_json(
                "https://launchermeta.mojang.com/mc/game/version_manifest.json",
                timeout=10,
            )
            if not manifest:
                return None
            ver_url = next(v["url"] for v in manifest["versions"] if v["id"] == mc_version)
            ver_data = HTTPUtils.get_json(ver_url, timeout=10)
            if not ver_data:
                return None
            return ver_data["downloads"]["server"]["url"]
        except Exception as e:
            logger.exception(f"獲取 Minecraft 伺服器 URL 失敗: {e}")
            return None

    def _standardize_loader_type(self, lt: str, loader_version: str) -> str:
        """標準化載入器類型：將輸入轉為小寫並進行基本推斷。
        Standardize loader type: convert input to lowercase and make basic inferences.

        Args:
            lt: 載入器類型
            loader_version: 載入器版本

        Returns:
            標準化後的載入器類型

        """
        return ServerDetectionUtils.standardize_loader_type(lt, loader_version)

    def _fail(self, progress_callback, user_msg: str, debug: str = "") -> bool:
        """通用失敗處理：顯示錯誤訊息並回傳 False。
        Generic failure handler: show error message and return False.

        Args:
            progress_callback: 進度回調函數
            user_msg: 用戶端顯示的錯誤訊息
            debug: 除錯訊息

        Returns:
            是否成功

        """
        if debug:
            logger.debug(debug)
        if progress_callback:
            progress_callback(100, user_msg)
        return False
