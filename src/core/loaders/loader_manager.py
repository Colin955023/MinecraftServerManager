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

from ...models import LoaderVersion
from ...utils import (
    CancellationToken,
    HTTPUtils,
    PathUtils,
    RuntimePaths,
    Singleton,
    SubprocessUtils,
    SystemUtils,
    atomic_write_json,
    get_logger,
    record_and_mark,
)
from .. import JavaManager, MinecraftVersionManager, ServerCommands, ServerDetectionUtils
from ..loaders.loader_adapter import ILoaderAdapter
from ..loaders.loader_fabric import FabricAdapter
from ..loaders.loader_forge import ForgeAdapter
from ..loaders.loader_neoforge import NeoForgeAdapter
from ..loaders.loader_quilt import QuiltAdapter


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
    SECURE_CHECKSUM_SUFFIXES: tuple[tuple[str, str], ...] = (
        ("sha256", ".sha256"),
        ("sha512", ".sha512"),
        ("sha1", ".sha1"),
    )

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
        self._adapters: dict[str, ILoaderAdapter] = {
            "fabric": FabricAdapter(),
            "forge": ForgeAdapter(),
            "neoforge": NeoForgeAdapter(),
            "quilt": QuiltAdapter(),
        }
        self._initialized = True

    def get_adapter(self, loader_type: str) -> ILoaderAdapter | None:
        return self._adapters.get(loader_type.lower())

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
        lt = ServerDetectionUtils.standardize_loader_type(loader_type, loader_version)
        java_path = None
        java_path_auto = False
        if user_java_path and Path(user_java_path).exists():
            java_path = user_java_path
        else:
            java_path = JavaManager.get_best_java_path(minecraft_version, ask_download=False)
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
        lt = ServerDetectionUtils.standardize_loader_type(loader_type, loader_version)
        adapter = self.get_adapter(lt)
        if adapter:
            return adapter.get_installer_url(minecraft_version, loader_version)
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

            for loader_type, adapter in self._adapters.items():
                cache_file = getattr(self, f"{loader_type}_cache_file", None)
                if not cache_file:
                    continue
                try:
                    data = adapter.fetch_remote_versions()
                    if data and not atomic_write_json(Path(cache_file), data):
                        logger.warning(f"寫入 {loader_type} 版本快取失敗")
                except Exception:
                    self._record_loader_cache_error(cache_file, f"載入 {loader_type} 版本失敗")

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

    def get_compatible_loader_versions(self, mc_version: str, loader_type: str) -> list[LoaderVersion]:
        """
        只從 json 快取檔案取得相容的載入器版本列表。

        Args:
            mc_version: Minecraft 版本。
            loader_type: 載入器類型。

        Returns:
            相容的載入器版本列表。
        """
        cache_key = f"{loader_type.lower()}_{mc_version}"
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]

        adapter = self.get_adapter(loader_type)
        if not adapter:
            return []

        cache_file = getattr(self, f"{loader_type.lower()}_cache_file", None)
        if not cache_file or not Path(cache_file).exists():
            return []

        try:
            cache_data = PathUtils.load_json(Path(cache_file))
            if cache_data is None:
                return []

            result = adapter.get_compatible_versions(cache_data, mc_version)
            if result:
                self._version_cache[cache_key] = result
            return result
        except Exception as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(cache_file),
                    reason=f"get_compatible_loader_versions_{loader_type}",
                    details={"mc_version": mc_version},
                )
            logger.exception(f"獲取 {loader_type} 版本時發生錯誤: {e}")
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
        api_checksum: tuple[str, str] | None = None
        vm = MinecraftVersionManager()
        download_info = vm.get_server_download_info(minecraft_version)
        if download_info:
            server_url, api_sha1 = download_info
            if api_sha1:
                api_checksum = ("sha1", api_sha1)
                logger.info(f"已從 Mojang API 取得伺服器驗證資訊: algorithm=sha1, version={minecraft_version}")
        else:
            server_url = vm.get_server_download_url(minecraft_version) or self._get_minecraft_server_url(
                minecraft_version
            )
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
            api_checksum=api_checksum,
        )

    @staticmethod
    def _parse_remote_checksum_payload(payload: bytes | str | None, algorithm: str) -> str:
        """解析遠端 checksum 檔案內容。"""
        if payload is None:
            return ""
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        expected_length = (
            40 if algorithm == "sha1" else 64 if algorithm == "sha256" else 128 if algorithm == "sha512" else 0
        )
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
        api_checksum: tuple[str, str] | None = None,
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

        checksum: tuple[str, str] | None = None
        if api_checksum:
            checksum = api_checksum
            logger.info(f"使用 API 提供的驗證資訊: algorithm={api_checksum[0]}, url={url}")
        else:
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
