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

from ...models import LoaderVersion
from ...utils import (
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
    get_logger,
    record_and_mark,
)
from ..version_manager import MinecraftVersionManager
from .fabric_family_adapter import FabricAdapter, QuiltAdapter
from .forge_family_adapter import ForgeAdapter, NeoForgeAdapter


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

        self.adapters = {
            "fabric": FabricAdapter(self),
            "forge": ForgeAdapter(self),
            "quilt": QuiltAdapter(self),
            "neoforge": NeoForgeAdapter(self),
        }

        self._initialized = True

    def _get_adapter(self, loader_type: str, loader_version: str = ""):
        lt = ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version)
        return self.adapters.get(lt)

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
        """正規化版本字串為 'mc_version-loader_version' 的統一格式。"""
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
                    normalized_versions.append(f"{mc_clean}-{suffix_text}")
                elif mc_clean and len(mc_parts) > 3:
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

        lt = ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version)
        if lt == "vanilla":
            return self._download_vanilla_server(minecraft_version, download_path, progress_callback, cancel_flag)

        adapter = self._get_adapter(loader_type, loader_version)
        if not adapter:
            return self._fail(
                progress_callback,
                f"不支援或無法識別的載入器類型: {loader_type}",
                debug=f"[DEBUG] Unsupported loader_type={loader_type}",
            )

        java_path = None
        java_path_auto = False
        if user_java_path and Path(user_java_path).exists():
            java_path = user_java_path
        else:
            java_path = JavaUtils.get_best_java_path(minecraft_version, ask_download=False)
            java_path_auto = True
        if not java_path:
            return False

        if java_path_auto:
            logger.info(f"[Java偵測] 自動選用 java_path: {java_path}")

        if not adapter.is_installer_required():
            return self._download_vanilla_server(minecraft_version, download_path, progress_callback, cancel_flag)

        installer_url = adapter.get_installer_download_url(minecraft_version, loader_version)
        if not installer_url:
            return self._fail(progress_callback, f"找不到 {loader_type} 安裝器下載網址")

        installer_path = str(RuntimePaths.get_cache_dir() / f"{adapter.get_id()}-installer.jar")
        args = adapter.get_installer_args(java_path, minecraft_version, loader_version, download_path, installer_path)

        # Replace '{installer}' in args just in case (for backward compatibility if they used it)
        args = [a.replace("{installer}", installer_path) for a in args]

        return self._download_and_run_installer(
            installer_url=installer_url,
            installer_args=args,
            minecraft_version=minecraft_version,
            download_path=download_path,
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
            need_vanilla=adapter.needs_vanilla_jar(),
            loader_type=adapter.get_id(),
        )

    def get_installer_download_url(self, loader_type: str, minecraft_version: str, loader_version: str) -> str | None:
        adapter = self._get_adapter(loader_type, loader_version)
        if adapter:
            return adapter.get_installer_download_url(minecraft_version, loader_version)
        return None

    def preload_loader_versions(self):
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

            for adapter in self.adapters.values():
                adapter.preload_versions()

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
        numeric_parts = re.findall(r"\d+", str(version_text or ""))
        if not numeric_parts:
            return (0,)
        return tuple(int(part) for part in numeric_parts)

    @staticmethod
    def _build_neoforge_mc_version_candidates(mc_version: str) -> list[str]:
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

    def get_compatible_loader_versions(self, mc_version: str, loader_type: str) -> list[LoaderVersion]:
        adapter = self._get_adapter(loader_type)
        if adapter:
            return adapter.get_compatible_versions(mc_version)
        return []

    def _download_vanilla_server(self, minecraft_version, download_path, progress_callback, cancel_flag):
        """委派給 MinecraftVersionManager 處理"""
        vm = MinecraftVersionManager()
        return vm.download_server_jar(minecraft_version, download_path, progress_callback, cancel_flag)

    def _fail(self, progress_callback, msg: str, debug: str = "") -> bool:
        if progress_callback:
            progress_callback(msg)
        if debug:
            logger.debug(debug)
        else:
            logger.warning(msg)
        return False

    def _get_loader_installer_sha256(self, url: str) -> str | None:
        for _secure_algo, suffix in self.SECURE_CHECKSUM_SUFFIXES:
            sha_url = f"{url}{suffix}"
            sha_content = HTTPUtils.get_content(sha_url)
            if sha_content:
                parts = sha_content.decode("utf-8").strip().split()
                if parts:
                    return parts[0]
        return None

    def _download_and_run_installer(
        self,
        installer_url: str,
        installer_args: list[str],
        minecraft_version: str,
        download_path: str,
        progress_callback=None,
        cancel_flag: dict | None = None,
        need_vanilla: bool = False,
        loader_type: str = "loader",
    ) -> bool | str:

        if self._is_cancel_requested(cancel_flag):
            return False

        base_dir = Path(download_path).parents[0]
        installer_path = str(RuntimePaths.get_cache_dir() / f"{loader_type}-installer.jar")

        if need_vanilla:
            if progress_callback:
                progress_callback("正在準備原版伺服器檔案...")
            if not self._download_vanilla_server(
                minecraft_version, str(base_dir / "server.jar"), progress_callback, cancel_flag
            ):
                return False

        if self._is_cancel_requested(cancel_flag):
            return False

        if progress_callback:
            progress_callback(f"正在下載 {loader_type} 安裝器...")

        expected_hash = self._get_loader_installer_sha256(installer_url)

        if not HTTPUtils.download_file_with_progress(
            installer_url,
            installer_path,
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
            expected_hash=expected_hash,
            hash_algo="sha256" if expected_hash else None,
        ):
            return self._fail(progress_callback, f"下載 {loader_type} 安裝器失敗或被取消")

        if self._is_cancel_requested(cancel_flag):
            return False

        if progress_callback:
            progress_callback(f"正在執行 {loader_type} 安裝程序 (這可能需要幾分鐘)...")

        process = None
        try:
            process = SubprocessUtils.create_no_window_process(installer_args, cwd=str(base_dir))
            SystemUtils.register_managed_process(base_dir, process.pid)

            while process.poll() is None:
                if self._is_cancel_requested(cancel_flag):
                    process.cancelled = True
                    self._cleanup_failed_installer_process(
                        process,
                        base_dir=base_dir,
                        installer_path=installer_path,
                        reason=f"使用者取消了 {loader_type} 安裝程序",
                    )
                    return False
                time.sleep(0.5)

            if process.returncode != 0:
                stdout, stderr = process.communicate()
                out_str = stdout.decode("utf-8", errors="replace") if stdout else ""
                err_str = stderr.decode("utf-8", errors="replace") if stderr else ""
                logger.error(
                    f"{loader_type} 安裝程序失敗 (代碼 {process.returncode})\\nSTDOUT: {out_str}\\nSTDERR: {err_str}"
                )
                self._cleanup_failed_installer_process(
                    process,
                    base_dir=base_dir,
                    installer_path=installer_path,
                    reason=f"{loader_type} 安裝失敗",
                    details={"returncode": process.returncode, "stderr": err_str},
                )
                return self._fail(progress_callback, f"{loader_type} 安裝程序執行失敗，請查看日誌了解詳情。")

            with suppress(Exception):
                SystemUtils.unregister_managed_process(base_dir, process.pid)

            if progress_callback:
                progress_callback("安裝成功，正在清理臨時檔案...")

            if loader_type in ("forge", "neoforge"):
                ServerCommands.grant_execution_permission(str(base_dir))
                run_bat = base_dir / "run.bat"
                if run_bat.exists():
                    return "run.bat"
                return self._fail(progress_callback, f"{loader_type} 安裝完成但找不到啟動腳本 (run.bat)")

            return True

        except Exception as e:
            logger.exception(f"執行 {loader_type} 安裝器時發生錯誤: {e}")
            self._cleanup_failed_installer_process(
                process,
                base_dir=base_dir,
                installer_path=installer_path,
                reason=f"執行 {loader_type} 安裝程序發生例外",
                details={"error": str(e)},
            )
            return self._fail(progress_callback, f"執行 {loader_type} 安裝器時發生錯誤：{e}")
