"""
模組載入器管理器。

負責處理 Fabric、Forge、Quilt、NeoForge 載入器的版本管理與下載，支援自動取得最新版本資訊並提供相容性檢查。
"""

import re
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree as ET

from ..models import LoaderVersion
from ..utils import (
    CancellationToken,
    HTTPUtils,
    JavaUtils,
    PathUtils,
    RuntimePaths,
    ServerCommands,
    ServerDetectionVersionUtils,
    Singleton,
    SubprocessUtils,
    SystemUtils,
    atomic_write_json,
    get_logger,
    record_and_mark,
)
from . import MinecraftVersionManager


@dataclass
class OperationResult:
    """通用操作結果類別，用於統一表示方法執行的成功與失敗狀態，以及相關訊息和錯誤資訊。"""

    success: bool
    message: str = ""
    error: Exception | None = None
    extra: dict = field(default_factory=dict)


logger = get_logger().bind(component="LoaderManager")


class LoaderManager(Singleton):
    """模組載入器管理器類別，管理 Fabric 和 Forge 載入器版本"""

    _initialized: bool = False
    LOADER_CACHE_TTL_SECONDS: int = 12 * 60 * 60
    SECURE_CHECKSUM_SUFFIXES: tuple[tuple[str, str], ...] = (("sha256", ".sha256"), ("sha512", ".sha512"))

    def __init__(self):
        if self._initialized:
            return
        cache_dir = RuntimePaths.ensure_dir(RuntimePaths.get_cache_dir())
        self.fabric_cache_file = str(cache_dir / "fabric_versions_cache.json")
        self.forge_cache_file = str(cache_dir / "forge_versions_cache.json")
        self.quilt_cache_file = str(cache_dir / "quilt_versions_cache.json")
        self.neoforge_cache_file = str(cache_dir / "neoforge_versions_cache.json")
        self._version_cache = {}
        self._preload_lock = threading.Lock()
        self._preloaded_once = False
        self._initialized = True

    def clear_cache_file(self):
        """
        通用快取檔案清除方法。

        Returns:
            OperationResult: 包含成功狀態、訊息和錯誤資訊的操作結果物件。
        """
        try:
            for cache_attr in ("fabric_cache_file", "forge_cache_file", "quilt_cache_file", "neoforge_cache_file"):
                cache_path = getattr(self, cache_attr, None)
                if cache_path:
                    Path(cache_path).unlink(missing_ok=True)
            self._version_cache.clear()
            self._preloaded_once = False
            return OperationResult(True, "快取檔案已成功清除")
        except PermissionError as e:
            logger.exception(f"清除快取檔案失敗: {e}")
            return OperationResult(False, f"無法刪除快取檔案\n權限不足\n{e}", error=e)
        except OSError as e:
            logger.exception(f"清除快取檔案失敗 (IO): {e}")
            return OperationResult(False, f"無法刪除快取檔案\n{e}", error=e)

    @staticmethod
    def _is_cancel_requested(cancel_flag: dict | CancellationToken | None) -> bool:
        """統一判斷目前流程是否已被要求取消。"""
        if not cancel_flag:
            return False
        try:
            if hasattr(cancel_flag, "is_cancelled") and callable(cancel_flag.is_cancelled):
                return bool(cancel_flag.is_cancelled())
            if isinstance(cancel_flag, dict):
                return bool(cancel_flag.get("cancelled"))
            if hasattr(cancel_flag, "cancelled"):
                return bool(cancel_flag.cancelled)
        except Exception:
            return False
        return False

    def _cleanup_failed_installer_process(
        self,
        process,
        *,
        base_dir: Path,
        installer_path: str,
        reason: str,
        details: dict | None = None,
    ) -> None:
        """在 installer 失敗或取消時清理殘留進程。"""
        if process is None:
            return
        pid = int(getattr(process, "pid", 0) or 0)
        try:
            is_running = process.poll() is None
            if pid and (is_running or bool(getattr(process, "cancelled", False))):
                SystemUtils.kill_process_tree(pid)
        except Exception as e:
            logger.warning(f"終止安裝器進程樹失敗: {e}")
        try:
            SystemUtils.kill_java_processes_in_path(base_dir)
        except Exception as e:
            logger.warning(f"清理安裝器殘留 Java 進程失敗: {e}")
        with suppress(Exception):
            SystemUtils.unregister_managed_process(base_dir, pid)
        with suppress(Exception):
            record_and_mark(
                RuntimeError(reason),
                Path(installer_path),
                reason=reason,
                details=details or {"installer": installer_path, "base_dir": str(base_dir)},
            )

    @staticmethod
    def _extract_stable_version_strings(content: bytes) -> list[str]:
        root = ET.fromstring(content)
        versions: list[str] = []
        for version_elem in root.findall(".//version"):
            version_text = version_elem.text
            if version_text and "-" in version_text:
                lower_text = version_text.lower()
                test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                if any(keyword in lower_text for keyword in test_keywords):
                    continue
                versions.append(version_text.strip())
        return versions

    @staticmethod
    def _extract_all_version_strings(content: bytes) -> list[str]:
        """
        從 maven metadata 或類似 XML 回傳中擷取所有版本字串（包含無 '-' 的版本）。

        支援兩種格式：
        - 含 '-' 的版本 (如 20.2.12-beta、26.1.2.36-beta)
        - 無 '-' 的版本 (如 20.4.167、21.0.143)
        """
        root = ET.fromstring(content)
        versions: list[str] = []
        for version_elem in root.findall(".//version"):
            version_text = version_elem.text
            if version_text:
                version_text = version_text.strip()
                versions.append(version_text)
        return versions

    @staticmethod
    def _normalize_version_strings(versions: list[str]) -> list[str]:
        """
        正規化版本字串為 'mc_version-loader_version' 的統一格式。

        支援格式：
        - Forge: 'X.Y.Z-A.B.C' → 'X.Y.Z-A.B.C' (保持完整)
        - NeoForge: '21.1.165' → '1.21.1-21.1.165'
        - NeoForge (完整+後綴): '1.21.1.21.1.165-beta' → '1.21.1-21.1.165-beta'
        - Fabric/其他: 根據實際格式調整
        """
        normalized_versions: list[str] = []
        for version in versions:
            if "-" in version:
                parts = version.split("-", 1)
                mc_part = parts[0]
                suffix_part = parts[1]

                mc_clean = re.sub("[^0-9.]", "", mc_part).rstrip(".")
                suffix_clean = re.sub("[^0-9.]", "", suffix_part).rstrip(".")
                mc_parts = [part for part in mc_clean.split(".") if part]

                suffix_text = suffix_part.strip().rstrip(".")
                suffix_has_label = bool(re.search("[A-Za-z]", suffix_text))

                if mc_clean and suffix_clean and mc_parts and mc_parts[0] == "1" and len(mc_parts) <= 3:
                    # 已是 MC-loader 格式，保留 loader 端的 beta/rc 標籤。
                    normalized_versions.append(f"{mc_clean}-{suffix_text}")
                elif mc_clean and len(mc_parts) > 3:
                    # NeoForge 可能把 MC 版本與 loader 版本接在同一段，再用 beta/rc 作後綴。
                    if mc_parts[0] == "1" and len(mc_parts) >= 6:
                        loader_version = ".".join(mc_parts[3:])
                        if suffix_text:
                            loader_version = f"{loader_version}-{suffix_text}"
                        normalized_versions.append(f"{'.'.join(mc_parts[:3])}-{loader_version}")
                    elif mc_parts[0] in {"20", "21"} and len(mc_parts) >= 3:
                        loader_version = ".".join(mc_parts)
                        if suffix_text:
                            loader_version = f"{loader_version}-{suffix_text}"
                        normalized_versions.append(f"1.{mc_parts[0]}.{mc_parts[1]}-{loader_version}")
                elif mc_clean and mc_parts and mc_parts[0] in {"20", "21"} and len(mc_parts) >= 3 and suffix_has_label:
                    normalized_versions.append(f"1.{mc_parts[0]}.{mc_parts[1]}-{mc_clean}-{suffix_text}")
                elif mc_clean and suffix_clean:
                    # 兩邊都有數字：使用 Forge 格式保持完整 (e.g., "26.1.2-64.0.7")
                    normalized_versions.append(f"{mc_clean}-{suffix_clean}")
                elif mc_clean:
                    normalized_versions.append(version)
            else:
                version_clean = re.sub("[^0-9.]", "", version).rstrip(".")
                if version_clean:
                    parts = version_clean.split(".")
                    if len(parts) >= 6 and parts[0] == "1":
                        normalized_versions.append(f"{'.'.join(parts[:3])}-{'.'.join(parts[3:])}")
                    elif len(parts) >= 3 and parts[0] in {"20", "21"}:
                        normalized_versions.append(f"1.{parts[0]}.{parts[1]}-{version_clean}")
                    elif len(parts) >= 3:
                        mc_version = f"{parts[0]}.{parts[1]}"
                        loader_version = parts[-1]
                        normalized_versions.append(f"{mc_version}-{loader_version}")
                    elif len(parts) == 2:
                        normalized_versions.append(version_clean)
        return normalized_versions

    def _build_loader_version_dict_from_metadata(
        self, content: bytes, allow_prerelease: bool = False
    ) -> dict[str, list[str]]:
        """
        從 metadata content 建立 mc_version -> [mc-version-loader-version,...] 的字典。

        如果 allow_prerelease 為 True，將包含 pre-release/beta 版本；否則預設只包含 stable。
        """
        if allow_prerelease:
            versions = self._extract_all_version_strings(content)
        else:
            versions = self._extract_stable_version_strings(content)
        normalized_versions = self._normalize_version_strings(versions)
        if not normalized_versions:
            return {}
        return self._build_version_dict_from_strings(normalized_versions)

    @staticmethod
    def _build_version_dict_from_strings(filtered_versions: list[str]) -> dict[str, list[str]]:
        version_dict: dict[str, list[str]] = {}
        for version in filtered_versions:
            if "-" in version:
                try:
                    parts = version.split("-", 1)
                    if len(parts) == 2:
                        mc_version = parts[0]
                        mc_parts = mc_version.split(".")
                        if len(mc_parts) == 4:
                            mc_version = ".".join(mc_parts[:3])
                        if mc_version not in version_dict:
                            version_dict[mc_version] = []
                        version_dict[mc_version].append(version)
                except (ValueError, IndexError) as e:
                    logger.debug(f"解析版本字串失敗 '{version}': {e}", "LoaderManager")
                    continue
        return version_dict

    @staticmethod
    def _record_loader_cache_error(cache_file: str | Path, reason: str, details: dict | None = None) -> None:
        with suppress(Exception):
            record_and_mark(
                RuntimeError(reason),
                Path(cache_file),
                reason=reason,
                details=details or {"cache_file": str(cache_file)},
            )

    @staticmethod
    def _load_version_objects_from_cache(cache_path: str | Path) -> list[LoaderVersion]:
        cache = PathUtils.load_json(Path(cache_path))
        if not cache:
            return []
        result: list[LoaderVersion] = []
        for item in cache:
            if isinstance(item, dict) and "version" in item:
                ver = item["version"]
                if ver:
                    result.append(LoaderVersion(version=ver))
        return result

    def download_server_jar_with_progress(
        self,
        loader_type: str,
        minecraft_version: str,
        loader_version: str,
        download_path: str,
        progress_callback=None,
        cancel_flag: dict | None = None,
        user_java_path: str | None = None,
    ) -> bool | str:
        """
        依 loader_type 下載並部署伺服器檔案。

        Args:
            loader_type: 載入器類型。
            minecraft_version: Minecraft 版本。
            loader_version: 載入器版本。
            download_path: 伺服器下載目標路徑。
            progress_callback: 下載進度回呼。
            cancel_flag: 可選的取消旗標。
            user_java_path: 使用者指定的 Java 路徑。

        Returns:
            Vanilla / Fabric 成功時回傳 bool；Forge 成功時回傳主 JAR 的相對路徑字串。
        """
        lt = ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version)
        java_path = None
        java_path_auto = False
        if user_java_path and Path(user_java_path).exists():
            java_path = user_java_path
        else:
            java_path = JavaUtils.get_best_java_path(minecraft_version, ask_download=False)
            java_path_auto = True
        if not java_path:
            return False
        # [3] 若 java_path 是自動偵測，於 log 補全
        if java_path_auto:
            logger.info(f"[Java偵測] 自動選用 java_path: {java_path}")
        if lt == "vanilla":
            return self._download_vanilla_server(minecraft_version, download_path, progress_callback, cancel_flag)
        installer_url = self.get_installer_download_url(lt, minecraft_version, loader_version)
        if not installer_url:
            return self._fail(progress_callback, f"找不到 {loader_type} 安裝器下載網址")
        if lt == "fabric":
            return self._download_and_run_installer(
                installer_url=installer_url,
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
                    str(Path(download_path).parents[0]),
                ],
                minecraft_version=minecraft_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                need_vanilla=True,
                loader_type="fabric",
            )
        if lt in ("forge", "neoforge"):
            return self._download_and_run_installer(
                installer_url=installer_url,
                installer_args=[java_path, "-jar", "{installer}", "--installServer"],
                minecraft_version=minecraft_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                need_vanilla=False,
                loader_type=lt,
            )
        if lt == "quilt":
            return self._download_and_run_installer(
                installer_url=installer_url,
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
                    str(Path(download_path).parents[0]),
                ],
                minecraft_version=minecraft_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                need_vanilla=True,
                loader_type="quilt",
            )
        return self._fail(
            progress_callback,
            f"目前僅支援 Vanilla / Fabric / Forge / Quilt / NeoForge，無法下載載入器類型: {loader_type}",
            debug=f"[DEBUG] Unsupported loader_type={loader_type}",
        )

    def get_installer_download_url(self, loader_type: str, minecraft_version: str, loader_version: str) -> str | None:
        """
        取得建立伺服器時所需的安裝器下載 URL。

        Args:
            loader_type: 載入器類型。
            minecraft_version: Minecraft 版本。
            loader_version: 載入器版本。

        Returns:
            安裝器下載 URL；若不支援則回傳 None。
        """
        lt = ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version)
        if lt == "fabric":
            return "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.1/fabric-installer-1.1.1.jar"
        if lt == "forge":
            return (
                f"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraft_version}-{loader_version}/"
                f"forge-{minecraft_version}-{loader_version}-installer.jar"
            )
        if lt == "neoforge":
            full_version = loader_version.strip()
            return (
                f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{full_version}/"
                f"neoforge-{full_version}-installer.jar"
            )
        if lt == "quilt":
            return self._get_quilt_installer_url()
        return None

    def preload_loader_versions(self):
        """
        從 API 取得所有載入器版本並覆蓋寫入 json。
        """
        with self._preload_lock:
            cache_exists = self._loader_cache_files_exist()
            cache_fresh = self._loader_cache_is_fresh()
            if not self._preloaded_once and cache_fresh:
                logger.debug("載入器快取仍在有效期內，本輪略過預抓")
                self._preloaded_once = True
                return
            if self._preloaded_once and cache_exists and cache_fresh:
                logger.debug("載入器版本已預抓且快取有效，略過重複預抓")
                return
            if not cache_exists:
                logger.debug("偵測到載入器快取缺失，執行重新預抓")
            elif not cache_fresh:
                logger.debug("載入器快取已過期，執行重新預抓")
            self._preload_fabric_versions()
            self._preload_forge_versions()
            self._preload_quilt_versions()
            self._preload_neoforge_versions()
            self._preloaded_once = True

    def _loader_cache_files_exist(self) -> bool:
        for cache_attr in ("fabric_cache_file", "forge_cache_file", "quilt_cache_file", "neoforge_cache_file"):
            cache_path = getattr(self, cache_attr, None)
            if not cache_path or not Path(cache_path).exists():
                return False
        return True

    def _loader_cache_is_fresh(self) -> bool:
        if not self._loader_cache_files_exist():
            return False
        now = time.time()
        ttl_seconds = max(1, int(self.LOADER_CACHE_TTL_SECONDS))
        newest_allowed_age = ttl_seconds
        try:
            fabric_age = now - Path(self.fabric_cache_file).stat().st_mtime
            forge_age = now - Path(self.forge_cache_file).stat().st_mtime
            quilt_age = now - Path(self.quilt_cache_file).stat().st_mtime
            neoforge_age = now - Path(self.neoforge_cache_file).stat().st_mtime
        except OSError:
            return False
        return (
            fabric_age <= newest_allowed_age
            and forge_age <= newest_allowed_age
            and quilt_age <= newest_allowed_age
            and neoforge_age <= newest_allowed_age
        )

    @staticmethod
    def _parse_forge_version_tuple(version_text: str) -> tuple[int, ...]:
        """
        將 Forge 版本字串轉成可比較的數值 tuple。

        目前採用純數字段拆解並逐段整數比較，適合常見 `x.y.z` 版本。
        對包含複雜 pre-release metadata 的語意版本規則，僅提供近似排序能力。
        """
        numeric_parts = re.findall("\\d+", str(version_text or ""))
        if not numeric_parts:
            return (0,)
        return tuple(int(part) for part in numeric_parts)

    @staticmethod
    def _build_neoforge_mc_version_candidates(mc_version: str) -> list[str]:
        """建立 NeoForge 快取查詢候選版本鍵，處理 `1.20.1` 與 `20.1` 的格式差異。"""
        normalized = str(mc_version or "").strip()
        if not normalized:
            return []
        candidates: list[str] = [normalized]
        normalized_parts = normalized.split(".")
        if len(normalized_parts) >= 2:
            candidates.append(f"{normalized_parts[0]}.{normalized_parts[1]}")
        if len(normalized_parts) >= 3:
            candidates.append(".".join(normalized_parts[:3]))
        if normalized.startswith("1."):
            tail = normalized[2:]
            if tail:
                candidates.append(tail)
            tail_parts = tail.split(".") if tail else []
            if tail_parts and tail_parts[0] in {"20", "21"}:
                if len(tail_parts) == 1:
                    candidates.append(f"{tail_parts[0]}.0")
                else:
                    candidates.append(f"{tail_parts[0]}.{tail_parts[1]}")
                if len(tail_parts) >= 2:
                    candidates.append(f"{tail_parts[0]}.{tail_parts[1]}.0.0")
        elif len(normalized_parts) >= 2 and normalized_parts[0].isdigit() and normalized_parts[1].isdigit():
            candidates.append(f"{normalized_parts[0]}.{normalized_parts[1]}.0.0")
        unique_candidates: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique_candidates:
                unique_candidates.append(candidate)
        return unique_candidates

    def _preload_fabric_versions(self) -> OperationResult:
        """從 API 取得 Fabric 載入器版本並覆蓋寫入 json（只保留 stable 版本）。"""
        logger.debug("預先抓取 Fabric 載入器版本...", "LoaderManager")
        fabric_url = "https://meta.fabricmc.net/v2/versions/loader"
        try:
            data = HTTPUtils.get_json(fabric_url, timeout=15)
            if data:
                stable_versions = [v for v in data if v.get("stable", False)]
                logger.debug(f"Fabric 版本過濾: {len(data)} -> {len(stable_versions)} (只保留 stable)")
                fabric_path = Path(self.fabric_cache_file)
                if not atomic_write_json(fabric_path, stable_versions):
                    logger.warning("寫入 Fabric 版本快取失敗")
            return OperationResult(True, "Fabric 版本預載完成")
        except (OSError, ValueError) as e:
            self._record_loader_cache_error(
                self.fabric_cache_file, "載入 Fabric 版本失敗", {"context": "_preload_fabric_versions"}
            )
            logger.exception(f"載入 Fabric 版本失敗（IO/解析）: {e}")
            return OperationResult(False, f"無法從 API 獲取 Fabric 版本：{e}", error=e)
        except Exception as e:
            self._record_loader_cache_error(self.fabric_cache_file, "載入 Fabric 版本失敗", {"url": fabric_url})
            logger.exception(f"載入 Fabric 版本失敗: {e}")
            return OperationResult(False, f"無法從 API 獲取 Fabric 版本：{e}", error=e)

    def _preload_forge_versions(self) -> None:
        logger.debug("預先抓取  Forge 載入器版本...", "LoaderManager")
        try:
            forge_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
            content = HTTPUtils.get_content(forge_url, timeout=15)
            if content:
                logger.debug("成功獲取 Forge XML 數據", "LoaderManager")
                version_dict = self._build_loader_version_dict_from_metadata(content)
                logger.debug(f"Forge 版本過濾後: {len(version_dict)} 個穩定版本群組")
                if version_dict:
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(
                            key=lambda full_version: (
                                self._parse_forge_version_tuple(full_version.split("-", 1)[1])
                                if "-" in full_version
                                else (0,),
                                full_version,
                            ),
                            reverse=True,
                        )
                        version_dict[mc_version] = version_dict[mc_version][:5]
                    forge_path = Path(self.forge_cache_file)
                    if not atomic_write_json(forge_path, version_dict):
                        logger.warning("寫入 Forge 版本快取失敗")
                    return
            return
        except (OSError, ET.ParseError, ValueError) as e:
            self._record_loader_cache_error(
                self.forge_cache_file, "載入 Forge 版本失敗", {"context": "_preload_forge_versions"}
            )
            logger.exception(f"Maven metadata API 方法失敗（IO/解析）: {e}")
            return
        except Exception as e:
            self._record_loader_cache_error(self.forge_cache_file, "載入 Forge 版本失敗")
            logger.exception(f"Maven metadata API 方法失敗: {e}")
            return

    def _preload_quilt_versions(self) -> OperationResult:
        """從 API 取得 Quilt 載入器版本並覆蓋寫入 json（只保留 stable 版本）。"""
        logger.debug("預先抓取 Quilt 載入器版本...", "LoaderManager")
        quilt_url = "https://meta.quiltmc.org/v3/versions/loader"
        try:
            data = HTTPUtils.get_json(quilt_url, timeout=15)
            if data:
                # 優先使用官方 stable 標記；若沒有 stable 欄位或結果為空，使用版本字串偵測排除 pre-release
                stable_versions = [v for v in data if v.get("stable", False)]
                if not stable_versions:
                    test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                    fallback = [
                        v
                        for v in data
                        if isinstance(v, dict)
                        and "version" in v
                        and not any(k in v["version"].lower() for k in test_keywords)
                    ]
                    chosen = fallback
                    logger.debug(
                        f"Quilt metadata 未提供 stable 標記或結果為空，採用版本字串過濾: {len(data)} -> {len(chosen)}"
                    )
                else:
                    chosen = stable_versions
                    logger.debug(f"Quilt 版本過濾: {len(data)} -> {len(chosen)} (使用 stable 標記)")

                if chosen:
                    chosen.sort(
                        key=lambda item: (
                            self._parse_forge_version_tuple(str(item.get("version", ""))),
                            int(item.get("build", 0) or 0),
                        ),
                        reverse=True,
                    )
                    chosen = chosen[:1]

                quilt_cache_file = getattr(self, "quilt_cache_file", "")
                quilt_path = (
                    Path(quilt_cache_file)
                    if quilt_cache_file
                    else Path(self.fabric_cache_file).with_name("quilt_versions_cache.json")
                )
                try:
                    wrote = atomic_write_json(quilt_path, chosen)
                    if wrote:
                        logger.debug(f"寫入 Quilt 版本快取: {quilt_path}，項目數={len(chosen)}")
                    else:
                        logger.warning(f"寫入 Quilt 版本快取失敗: {quilt_path}")
                except Exception as e:
                    logger.exception(f"嘗試寫入 Quilt 快取時發生例外: {e}")
            else:
                logger.debug("Quilt metadata 回傳空資料，未寫入快取")
            return OperationResult(True, "Quilt 版本預載完成")
        except (OSError, ValueError) as e:
            quilt_cache_file = getattr(
                self, "quilt_cache_file", Path(self.fabric_cache_file).with_name("quilt_versions_cache.json")
            )
            self._record_loader_cache_error(
                quilt_cache_file, "載入 Quilt 版本失敗", {"context": "_preload_quilt_versions"}
            )
            logger.exception(f"載入 Quilt 版本失敗（IO/解析）: {e}")
            return OperationResult(False, f"無法從 API 獲取 Quilt 版本：{e}", error=e)
        except Exception as e:
            quilt_cache_file = getattr(
                self, "quilt_cache_file", Path(self.fabric_cache_file).with_name("quilt_versions_cache.json")
            )
            self._record_loader_cache_error(quilt_cache_file, "載入 Quilt 版本失敗", {"url": quilt_url})
            logger.exception(f"載入 Quilt 版本失敗: {e}")
            return OperationResult(False, f"無法從 API 獲取 Quilt 版本：{e}", error=e)

    @staticmethod
    def _get_latest_quilt_installer_version() -> str | None:
        """取得 Quilt installer 的最新版本。"""
        metadata_url = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/maven-metadata.xml"
        try:
            content = HTTPUtils.get_content(metadata_url, timeout=15)
            if not content:
                return None
            root = ET.fromstring(content)
            release_version = root.findtext(".//versioning/release") or root.findtext(".//versioning/latest")
            if release_version:
                return release_version.strip()
        except (OSError, ET.ParseError, ValueError) as e:
            logger.exception(f"讀取 Quilt installer metadata 失敗（IO/解析）: {e}")
        except Exception as e:
            logger.exception(f"讀取 Quilt installer metadata 失敗: {e}")
        return None

    def _get_quilt_installer_url(self) -> str:
        """組出可下載的 Quilt installer URL。"""
        installer_version = self._get_latest_quilt_installer_version() or "0.12.1"
        return (
            f"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
            f"{installer_version}/quilt-installer-{installer_version}.jar"
        )

    def _preload_neoforge_versions(self) -> None:
        logger.debug("預先抓取 NeoForge 載入器版本...", "LoaderManager")
        try:
            neoforge_url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
            content = HTTPUtils.get_content(neoforge_url, timeout=15)
            if content:
                logger.debug("成功獲取 NeoForge XML 數據", "LoaderManager")
                # NeoForge 目前多為 beta/pre-release 版本，因此允許包含 pre-release
                version_dict = self._build_loader_version_dict_from_metadata(content, allow_prerelease=True)
                group_count = len(version_dict)
                total_versions = sum(len(v) for v in version_dict.values()) if version_dict else 0
                logger.debug(f"NeoForge 解析後: groups={group_count} total_versions={total_versions}")
                if group_count > 0:
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(
                            key=lambda full_version: (
                                self._parse_forge_version_tuple(full_version.split("-", 1)[1])
                                if "-" in full_version
                                else self._parse_forge_version_tuple(full_version),
                                full_version,
                            ),
                            reverse=True,
                        )
                        # 僅保留最新 5 個版本（使用排序後的前五項）
                        version_dict[mc_version] = version_dict[mc_version][:5]
                    neoforge_cache_file = getattr(self, "neoforge_cache_file", "")
                    neoforge_path = (
                        Path(neoforge_cache_file)
                        if neoforge_cache_file
                        else Path(self.forge_cache_file).with_name("neoforge_versions_cache.json")
                    )
                    try:
                        wrote = atomic_write_json(neoforge_path, version_dict)
                        if wrote:
                            logger.debug(
                                f"寫入 NeoForge 版本快取: {neoforge_path} groups={group_count} total_versions={total_versions}"
                            )
                        else:
                            logger.warning(f"寫入 NeoForge 版本快取失敗: {neoforge_path}")
                    except Exception as e:
                        logger.exception(f"嘗試寫入 NeoForge 快取時發生例外: {e}")
                    return
            return
        except (OSError, ET.ParseError, ValueError) as e:
            neoforge_cache_file = getattr(
                self, "neoforge_cache_file", Path(self.forge_cache_file).with_name("neoforge_versions_cache.json")
            )
            self._record_loader_cache_error(
                neoforge_cache_file, "載入 NeoForge 版本失敗", {"context": "_preload_neoforge_versions"}
            )
            logger.exception(f"Maven metadata API 方法失敗（IO/解析）: {e}")
            return
        except Exception as e:
            neoforge_cache_file = getattr(
                self, "neoforge_cache_file", Path(self.forge_cache_file).with_name("neoforge_versions_cache.json")
            )
            self._record_loader_cache_error(neoforge_cache_file, "載入 NeoForge 版本失敗")
            logger.exception(f"Maven metadata API 方法失敗: {e}")
            return

    def get_compatible_loader_versions(self, mc_version: str, loader_type: str) -> list[LoaderVersion]:
        """
        只從 json 快取檔案取得相容的載入器版本列表。

        Args:
            mc_version (str): 要檢查的 MC 版本字串
            loader_type (str): 載入器類型（"fabric" 或 "forge"）

        Returns:
            List[LoaderVersion]: 相容的 Fabric 載入器版本列表
        """
        cache_key = f"{loader_type.lower()}_{mc_version}"
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        if not Path(self.fabric_cache_file).exists() and (not Path(self.forge_cache_file).exists()):
            return []
        if loader_type.lower() == "fabric":
            try:
                if not ServerDetectionVersionUtils.is_fabric_compatible_version(mc_version):
                    return []
                result = self._load_version_objects_from_cache(self.fabric_cache_file)
                if result:
                    self._version_cache[cache_key] = result
                return result
            except (OSError, ValueError, TypeError) as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.fabric_cache_file),
                        reason="get_compatible_loader_versions_fabric",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 Fabric 版本時發生錯誤（IO/解析）: {e}")
                return []
            except Exception as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.fabric_cache_file),
                        reason="get_compatible_loader_versions_fabric_unexpected",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 Fabric 版本時發生錯誤: {e}")
                return []
        elif loader_type.lower() == "forge":
            try:
                cache = PathUtils.load_json(Path(self.forge_cache_file))
                if not cache:
                    return []
                result = []
                if mc_version in cache and isinstance(cache[mc_version], list):
                    for version in cache[mc_version]:
                        if "-" in version and version.startswith(mc_version):
                            forge_version = version.split("-", 1)[1]
                            result.append(LoaderVersion(version=forge_version))
                if result:
                    self._version_cache[cache_key] = result
                return result
            except (OSError, ValueError, TypeError) as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.forge_cache_file),
                        reason="get_compatible_loader_versions_forge",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 Forge 版本時發生錯誤（IO/解析）: {e}")
                return []
            except Exception as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.forge_cache_file),
                        reason="get_compatible_loader_versions_forge_unexpected",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 Forge 版本時發生錯誤: {e}")
                return []
        elif loader_type.lower() == "quilt":
            try:
                if not ServerDetectionVersionUtils.is_fabric_compatible_version(mc_version):
                    return []
                result = self._load_version_objects_from_cache(self.quilt_cache_file)
                if result:
                    # 檢查 MC 版本是否在載入器支援的版本範圍內
                    filtered_result = []
                    for loader_ver in result:
                        if hasattr(loader_ver, "game_versions") and loader_ver.game_versions:
                            if mc_version in loader_ver.game_versions:
                                filtered_result.append(loader_ver)
                        else:
                            filtered_result.append(loader_ver)
                    if filtered_result:
                        self._version_cache[cache_key] = filtered_result
                        return filtered_result
                return []
            except (OSError, ValueError, TypeError) as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.quilt_cache_file),
                        reason="get_compatible_loader_versions_quilt",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 Quilt 版本時發生錯誤（IO/解析）: {e}")
                return []
            except Exception as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.quilt_cache_file),
                        reason="get_compatible_loader_versions_quilt_unexpected",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 Quilt 版本時發生錯誤: {e}")
                return []
        elif loader_type.lower() == "neoforge":
            try:
                cache = PathUtils.load_json(Path(self.neoforge_cache_file))
                if not cache:
                    return []
                result = []
                matched_key = ""
                for candidate in self._build_neoforge_mc_version_candidates(mc_version):
                    if candidate in cache and isinstance(cache[candidate], list):
                        matched_key = candidate
                        break
                if matched_key:
                    for version in cache[matched_key]:
                        if "-" in version and version.startswith(matched_key):
                            mc_prefix, neoforge_version = version.split("-", 1)
                            if "." not in neoforge_version and re.match(r"^(?:20|21)\.\d+$", mc_prefix):
                                neoforge_version = f"{mc_prefix}.{neoforge_version}"
                            result.append(LoaderVersion(version=neoforge_version))
                else:
                    logger.debug(
                        f"NeoForge 找不到相容版本群組: mc_version={mc_version}, "
                        f"candidates={self._build_neoforge_mc_version_candidates(mc_version)}"
                    )
                if result:
                    self._version_cache[cache_key] = result
                return result
            except (OSError, ValueError, TypeError) as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.neoforge_cache_file),
                        reason="get_compatible_loader_versions_neoforge",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 NeoForge 版本時發生錯誤（IO/解析）: {e}")
                return []
            except Exception as e:
                with suppress(Exception):
                    record_and_mark(
                        e,
                        Path(self.neoforge_cache_file),
                        reason="get_compatible_loader_versions_neoforge_unexpected",
                        details={"mc_version": mc_version},
                    )
                logger.exception(f"獲取 NeoForge 版本時發生錯誤: {e}")
                return []
        return []

    def _download_and_run_installer(
        self,
        installer_url: str,
        installer_args: list[str],
        minecraft_version: str,
        download_path: str,
        progress_callback,
        cancel_flag,
        need_vanilla: bool = False,
        loader_type: str = "",
    ) -> bool | str:
        """Fabric 與 Forge 共用：下載安裝器 → （Fabric 需先下載官方伺服器）→ 執行安裝器。"""
        base_dir = Path(download_path).parents[0]
        installer_path = str(base_dir / Path(installer_url).name)
        if need_vanilla:
            dl_start, dl_end = (10, 15)
            vanilla_start, vanilla_end = (15, 90)
            install_start = 90
        else:
            dl_start, dl_end = (10, 25)
            vanilla_start, vanilla_end = (0, 0)
            install_start = 25
        require_hash = loader_type.lower() not in ("forge", "neoforge")
        if not self._download_file_with_progress(
            installer_url,
            installer_path,
            progress_callback,
            dl_start,
            dl_end,
            "下載安裝器...",
            cancel_flag,
            require_secure_hash=require_hash,
        ):
            return False
        if need_vanilla and (
            not self._download_vanilla_server(
                minecraft_version,
                download_path,
                lambda p, s: (
                    progress_callback(vanilla_start + p * (vanilla_end - vanilla_start) / 100, s)
                    if progress_callback
                    else None
                ),
                cancel_flag,
            )
        ):
            return False
        if progress_callback:
            progress_callback(install_start, "準備執行安裝器...")
        cmd = [arg if arg != "{installer}" else installer_path for arg in installer_args]
        if not isinstance(cmd, list) or any(not isinstance(a, str) for a in cmd):
            logger.error(f"無效的安裝器命令參數: {cmd}")
            return self._fail(progress_callback, "執行安裝器失敗：無效的命令參數")
        process = None
        try:
            output_buffer = ""

            def _on_installer_started(pid: int) -> None:
                SystemUtils.register_managed_process(base_dir, pid)

            def _on_installer_output(chunk: str) -> None:
                nonlocal output_buffer
                output_buffer += chunk
                if not progress_callback:
                    return
                lines = output_buffer.splitlines()
                if output_buffer and not output_buffer.endswith(("\n", "\r")):
                    output_buffer = lines.pop() if lines else output_buffer
                else:
                    output_buffer = ""
                for raw_line in lines:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if "Download" in line:
                        progress_callback(install_start, f"安裝中: {line[:40]}...")
                    elif "Processor" in line:
                        progress_callback(install_start, f"處理中: {line[:40]}...")

            process = SubprocessUtils.run_qprocess_checked(
                cmd,
                cwd=str(base_dir),
                encoding="utf-8",
                on_started=_on_installer_started,
                on_stdout=_on_installer_output,
                cancel_check=lambda: self._is_cancel_requested(cancel_flag),
            )
            with suppress(Exception):
                SystemUtils.unregister_managed_process(base_dir, process.pid)
            if process.cancelled:
                self._cleanup_failed_installer_process(
                    process,
                    base_dir=base_dir,
                    installer_path=installer_path,
                    reason="installer_cancelled",
                    details={"cmd": cmd},
                )
                return self._fail(progress_callback, "已取消安裝，並已清理殘留安裝程序")
            if process.returncode != 0:
                logger.error(f"安裝器執行失敗 (Code {process.returncode})")
                return self._fail(
                    progress_callback,
                    f"安裝器執行失敗 (Code {process.returncode})",
                    debug=f"[DEBUG] cmd: {' '.join(cmd)}",
                )
        except (SubprocessUtils.CalledProcessError, OSError) as e:
            self._cleanup_failed_installer_process(
                process,
                base_dir=base_dir,
                installer_path=installer_path,
                reason="run_installer_failed_expected",
                details={"installer": installer_path, "cmd": cmd, "error": str(e)},
            )
            logger.exception(f"執行安裝器時發生可預期的子程序錯誤: {e}")
            return self._fail(
                progress_callback,
                f"執行安裝器時發生錯誤，並已嘗試清理殘留進程: {e}",
                debug=f"[DEBUG] Popen exception: {e}",
            )
        except Exception as e:
            self._cleanup_failed_installer_process(
                process,
                base_dir=base_dir,
                installer_path=installer_path,
                reason="run_installer_failed",
                details={"installer": installer_path, "cmd": cmd, "error": str(e)},
            )
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(installer_path),
                    reason="run_installer_failed",
                    details={"installer": installer_path, "cmd": cmd},
                )
            logger.exception(f"執行安裝器時發生錯誤: {e}")
            return self._fail(
                progress_callback,
                f"執行安裝器時發生錯誤，並已嘗試清理殘留進程: {e}",
                debug=f"[DEBUG] Popen exception: {e}",
            )
        try:
            run_bat_path = base_dir / "run.bat"
            run_sh_path = base_dir / "run.sh"
            start_server_path = base_dir / "start_server.bat"
            installer_log_path = base_dir / "installer.log"
            installer_java_exe = ServerCommands.to_console_java_executable(cmd[0] if cmd else None)
            java_line = None
            if run_bat_path.exists():
                try:
                    content = PathUtils.read_text_file(run_bat_path, errors="ignore")
                    if content:
                        for line in content.splitlines():
                            if re.search("\\bjavaw?(?:\\.exe)?\\b.*@user_jvm_args\\.txt\\b", line, re.IGNORECASE):
                                java_line = line.strip()
                                break
                    if java_line and installer_java_exe:
                        java_line, _ = ServerCommands.replace_java_command_line(java_line, installer_java_exe)
                    if java_line and "nogui" not in java_line.lower():
                        java_line += " nogui"
                except OSError as e:
                    logger.warning(f"無法讀取 run.bat (IO): {e}")
                    return False
                except Exception as e:
                    with suppress(Exception):
                        record_and_mark(
                            e,
                            Path(run_bat_path),
                            reason="read_run_bat_unexpected",
                            details={"path": str(run_bat_path)},
                        )
                    logger.exception(f"讀取 run.bat 時發生未預期錯誤: {e}")
                    return False
            if java_line and start_server_path.exists():
                try:
                    content = PathUtils.read_text_file(start_server_path, errors="ignore")
                    if content:
                        lines = content.splitlines(keepends=True)
                        new_lines = []
                        replaced = False
                        for line in lines:
                            if not replaced and re.match("^\\s*java\\b", line, re.IGNORECASE):
                                new_lines.append(java_line + "\n")
                                replaced = True
                            else:
                                new_lines.append(line)
                        PathUtils.write_text_file(start_server_path, "".join(new_lines))
                except OSError as e:
                    logger.exception(f"修改 start_server.bat 失敗（IO）: {e}")
                    return False
                except Exception as e:
                    with suppress(Exception):
                        record_and_mark(
                            e,
                            Path(start_server_path),
                            reason="modify_start_server_bat_unexpected",
                            details={"path": str(start_server_path)},
                        )
                    logger.exception(f"修改 start_server.bat 時發生未預期錯誤: {e}")
                    return False
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
            except OSError as e:
                logger.exception(f"清理安裝檔失敗（IO）: {installer_path}: {e}")
                logger.warning(f"安裝完成，但無法清理安裝器檔案：{installer_path}，可手動刪除。")
            except Exception as e:
                with suppress(Exception):
                    files_tried = [
                        str(run_bat_path),
                        str(run_sh_path),
                        str(base_dir / "README.txt"),
                        str(Path(installer_path)),
                        str(installer_log_path),
                    ]
                    record_and_mark(
                        e,
                        Path(installer_path),
                        reason="cleanup_installer_files_failed",
                        details={"installer": installer_path, "files": files_tried},
                    )
                logger.exception(f"清理安裝檔失敗: {installer_path}: {e}")
                logger.warning(f"安裝完成，但無法清理安裝器檔案：{installer_path}，可手動刪除。")
        except Exception as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(installer_path),
                    reason="installer_process_failed",
                    details={"installer": installer_path},
                )
            logger.exception(f"安裝過程中發生錯誤: {e}")
            return False
        return True

    def _download_vanilla_server(
        self, minecraft_version: str, download_path: str, progress_callback, cancel_flag
    ) -> bool:
        """下載 Minecraft 官方伺服器 JAR 檔案，供 Fabric 安裝流程使用。"""
        if progress_callback:
            progress_callback(10, "查詢 Minecraft 版本資訊...")
        server_url = MinecraftVersionManager().get_server_download_url(
            minecraft_version
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
            require_secure_hash=False,
        )

    @staticmethod
    def _parse_remote_checksum_payload(payload: bytes | str | None, algorithm: str) -> str:
        """解析遠端 checksum 檔案內容。"""
        if payload is None:
            return ""
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        expected_length = 64 if algorithm == "sha256" else 128 if algorithm == "sha512" else 0
        if expected_length <= 0:
            return ""
        for token in text.replace("*", " ").split():
            normalized = token.strip().lower()
            if len(normalized) == expected_length and all(ch in "0123456789abcdef" for ch in normalized):
                return normalized
        return ""

    @classmethod
    def _fetch_secure_checksum(cls, url: str) -> tuple[str, str] | None:
        """從常見 sidecar checksum URL 取得 SHA-256 / SHA-512。"""
        for algorithm, suffix in cls.SECURE_CHECKSUM_SUFFIXES:
            checksum_url = f"{url}{suffix}"
            try:
                payload = HTTPUtils.get_content(checksum_url, timeout=10, log_errors=False)
            except Exception as exc:
                logger.debug(f"讀取 checksum sidecar 失敗: {checksum_url} | {exc}")
                payload = None
            checksum = cls._parse_remote_checksum_payload(payload, algorithm)
            if checksum:
                logger.info(f"已取得下載檔案 checksum: algorithm={algorithm}, url={checksum_url}")
                return (algorithm, checksum)
        return None

    def _download_file_with_progress(
        self,
        url: str,
        dest_path: str,
        progress_callback,
        start_percent: int,
        end_percent: int,
        status_text: str,
        cancel_flag: dict | CancellationToken | None,
        require_secure_hash: bool = False,
    ) -> bool:
        """下載檔案並顯示進度。"""

        def on_progress(downloaded, total):
            if total > 0 and progress_callback:
                percent = start_percent + downloaded / total * (end_percent - start_percent)
                progress_callback(percent, status_text)

        def check_cancel():
            cancelled = self._is_cancel_requested(cancel_flag)
            if cancelled and progress_callback:
                self._fail(progress_callback, "已取消下載")
            return cancelled

        checksum = self._fetch_secure_checksum(url)
        if checksum is None and require_secure_hash:
            logger.error(f"下載失敗：找不到 SHA-256 / SHA-512 checksum sidecar，拒絕下載 {url}")
            return self._fail(progress_callback, "下載失敗：缺少 SHA-256 / SHA-512 驗證資訊")
        if checksum is None:
            logger.warning(f"下載檔案未找到 SHA-256 / SHA-512 sidecar，將僅使用既有來源保護: {url}")
        expected_hash = checksum[1] if checksum else None
        download_failure_reason = ""

        def _capture_download_failure(message: str) -> None:
            nonlocal download_failure_reason
            download_failure_reason = message

        if HTTPUtils.download_file(
            url,
            dest_path,
            progress_callback=on_progress,
            timeout=30,
            cancel_check=check_cancel,
            expected_hash=expected_hash,
            failure_message_callback=_capture_download_failure,
        ):
            return True
        return self._fail(progress_callback, download_failure_reason or "下載失敗：無法獲取檔案")

    def _get_minecraft_server_url(self, mc_version: str) -> str | None:
        """根據 Minecraft 版本獲取伺服器 JAR 下載 URL。"""
        try:
            manifest = HTTPUtils.get_json("https://launchermeta.mojang.com/mc/game/version_manifest.json", timeout=10)
            if not manifest:
                return None
            ver_url = next(v["url"] for v in manifest["versions"] if v["id"] == mc_version)
            ver_data = HTTPUtils.get_json(ver_url, timeout=10)
            if not ver_data:
                return None
            return ver_data["downloads"]["server"]["url"]
        except (OSError, StopIteration, KeyError, ValueError) as e:
            logger.exception(f"獲取 Minecraft 伺服器 URL 失敗（IO/解析）: {e}")
            return None
        except Exception as e:
            # 建立可觀測 marker（指向快取目錄下的 manifest 參考檔），以便後續診斷
            try:
                manifest_marker = Path(RuntimePaths.get_cache_dir()) / "version_manifest.json"
            except Exception:
                manifest_marker = None
            with suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=manifest_marker,
                    reason="get_minecraft_server_url_failed",
                    details={"mc_version": mc_version},
                )
            logger.exception(f"獲取 Minecraft 伺服器 URL 失敗: {e}")
            return None

    def _fail(self, progress_callback, user_msg: str, debug: str = "") -> bool:
        """通用失敗處理：顯示錯誤訊息並回傳 False。"""
        if debug:
            logger.debug(debug)
        if progress_callback:
            progress_callback(100, user_msg)
        return False
