"""模組載入器管理器。
負責處理 Fabric、Forge 載入器的版本管理與下載，支援自動取得最新版本資訊並提供相容性檢查。
"""

import re
import threading
import time
from contextlib import suppress
from pathlib import Path
from defusedxml import ElementTree as ET
from ..models import LoaderVersion
from ..utils import (
    HTTPUtils,
    JavaUtils,
    PathUtils,
    RuntimePaths,
    ServerDetectionVersionUtils,
    Singleton,
    SubprocessUtils,
    UIUtils,
    atomic_write_json,
    get_logger,
    record_and_mark,
    CancellationToken,
)
from . import MinecraftVersionManager

logger = get_logger().bind(component="LoaderManager")


class LoaderManager(Singleton):
    """模組載入器管理器類別，管理 Fabric 和 Forge 載入器版本"""

    _initialized: bool = False
    LOADER_CACHE_TTL_SECONDS: int = 12 * 60 * 60

    def __init__(self):
        if self._initialized:
            return
        cache_dir = RuntimePaths.ensure_dir(RuntimePaths.get_cache_dir())
        self.fabric_cache_file = str(cache_dir / "fabric_versions_cache.json")
        self.forge_cache_file = str(cache_dir / "forge_versions_cache.json")
        self._version_cache = {}
        self._preload_lock = threading.Lock()
        self._preloaded_once = False
        self._initialized = True

    def clear_cache_file(self):
        """通用快取檔案清除方法。"""
        try:
            fabric_path = Path(self.fabric_cache_file)
            forge_path = Path(self.forge_cache_file)
            fabric_path.unlink(missing_ok=True)
            forge_path.unlink(missing_ok=True)
            self._version_cache.clear()
            self._preloaded_once = False
        except PermissionError as e:
            logger.exception(f"清除快取檔案失敗: {e}")
            UIUtils.show_error("清除快取檔案失敗", f"無法刪除快取檔案\n權限不足\n{e}", topmost=True)
        except OSError as e:
            logger.exception(f"清除快取檔案失敗 (IO): {e}")
            UIUtils.show_error("清除快取檔案失敗", f"無法刪除快取檔案\n{e}", topmost=True)

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
        Vanilla/Fabric → bool；Forge → 成功時回傳主 JAR 相對路徑字串。
        """
        lt = self._standardize_loader_type(loader_type, loader_version)
        if user_java_path and Path(user_java_path).exists():
            java_path = user_java_path
        else:
            java_path = JavaUtils.get_best_java_path(minecraft_version, ask_download=True)
        if not java_path:
            return False
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
            installer_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraft_version}-{loader_version}/forge-{minecraft_version}-{loader_version}-installer.jar"
            return self._download_and_run_installer(
                installer_url=installer_url,
                installer_args=[java_path, "-jar", "{installer}", "--installServer"],
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
            f"目前僅支援 Vanilla / Fabric / Forge，無法下載載入器類型: {loader_type}",
            debug=f"[DEBUG] Unsupported loader_type={loader_type}",
        )

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
            self._preloaded_once = True

    def _loader_cache_files_exist(self) -> bool:
        return Path(self.fabric_cache_file).exists() and Path(self.forge_cache_file).exists()

    def _loader_cache_is_fresh(self) -> bool:
        if not self._loader_cache_files_exist():
            return False
        now = time.time()
        ttl_seconds = max(1, int(self.LOADER_CACHE_TTL_SECONDS))
        newest_allowed_age = ttl_seconds
        try:
            fabric_age = now - Path(self.fabric_cache_file).stat().st_mtime
            forge_age = now - Path(self.forge_cache_file).stat().st_mtime
        except OSError:
            return False
        return fabric_age <= newest_allowed_age and forge_age <= newest_allowed_age

    @staticmethod
    def _parse_forge_version_tuple(version_text: str) -> tuple[int, ...]:
        """將 Forge 版本字串轉成可比較的數值 tuple。

        目前採用純數字段拆解並逐段整數比較，適合常見 `x.y.z` 版本。
        對包含複雜 pre-release metadata 的語意版本規則，僅提供近似排序能力。
        """
        numeric_parts = re.findall("\\d+", str(version_text or ""))
        if not numeric_parts:
            return (0,)
        return tuple(int(part) for part in numeric_parts)

    def _preload_fabric_versions(self):
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
        except (OSError, ValueError) as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(self.fabric_cache_file),
                    reason="載入 Fabric 版本失敗",
                    details={"context": "_preload_fabric_versions"},
                )
            logger.exception(f"載入 Fabric 版本失敗（IO/解析）: {e}")
            UIUtils.show_error("載入 Fabric 版本失敗", f"無法從 API 獲取 Fabric 版本：{e}", topmost=True)
        except Exception as e:
            # 通用回退機制：記錄日誌、為快取檔建立檢查用的 marker，並回報給 UI
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(self.fabric_cache_file),
                    reason="載入 Fabric 版本失敗",
                    details={"url": fabric_url},
                )
            logger.exception(f"載入 Fabric 版本失敗: {e}")
            UIUtils.show_error("載入 Fabric 版本失敗", f"無法從 API 獲取 Fabric 版本：{e}", topmost=True)

    def _preload_forge_versions(self) -> None:
        logger.debug("預先抓取  Forge 載入器版本...", "LoaderManager")
        try:
            forge_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
            content = HTTPUtils.get_content(forge_url, timeout=15)
            if content:
                logger.debug("成功獲取 Forge XML 數據", "LoaderManager")
                root = ET.fromstring(content)
                versions = []
                for version_elem in root.findall(".//version"):
                    version_text = version_elem.text
                    if version_text and "-" in version_text:
                        lower_text = version_text.lower()
                        test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                        if any(keyword in lower_text for keyword in test_keywords):
                            continue
                        versions.append(version_text.strip())
                logger.debug(f"Forge 版本過濾後: {len(versions)} 個穩定版本")
                filtered_versions = []
                for v in versions:
                    parts = v.split("-", 1)
                    if len(parts) == 2:
                        mc_ver = re.sub("[^0-9.]", "", parts[0])
                        forge_ver = re.sub("[^0-9.]", "", parts[1])
                        if mc_ver and forge_ver:
                            filtered_versions.append(f"{mc_ver}-{forge_ver}")
                if len(filtered_versions) > 0:
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
                            except (ValueError, IndexError) as e:
                                logger.debug(f"解析 Forge 版本字串失敗 '{version}': {e}", "LoaderManager")
                                continue
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
                        version_dict[mc_version] = version_dict[mc_version][:10]
                    forge_path = Path(self.forge_cache_file)
                    if not atomic_write_json(forge_path, version_dict):
                        logger.warning("寫入 Forge 版本快取失敗")
                    return
            return
        except (OSError, ET.ParseError, ValueError) as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(self.forge_cache_file),
                    reason="載入 Forge 版本失敗",
                    details={"context": "_preload_forge_versions"},
                )
            logger.exception(f"Maven metadata API 方法失敗（IO/解析）: {e}")
            UIUtils.show_error("載入 Forge 版本失敗", f"無法從 Maven metadata API 獲取 Forge 版本：{e}", topmost=True)
            return
        except Exception as e:
            with suppress(Exception):
                record_and_mark(e, Path(self.forge_cache_file), reason="載入 Forge 版本失敗")
            logger.exception(f"Maven metadata API 方法失敗: {e}")
            UIUtils.show_error("載入 Forge 版本失敗", f"無法從 Maven metadata API 獲取 Forge 版本：{e}", topmost=True)
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
                cache = PathUtils.load_json(Path(self.fabric_cache_file))
                if not cache:
                    return []
                result = []
                for item in cache:
                    if isinstance(item, dict) and "version" in item:
                        ver = item["version"]
                        if ver:
                            result.append(LoaderVersion(version=ver))
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
        return []

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
        """Fabric 與 Forge 共用：下載安裝器 → （Fabric 需先下載官方伺服器）→ 執行安裝器。"""
        installer_path = str(Path(download_path).parent / Path(installer_url).name)
        if need_vanilla:
            dl_start, dl_end = (10, 15)
            vanilla_start, vanilla_end = (15, 90)
            install_start = 90
        else:
            dl_start, dl_end = (10, 25)
            vanilla_start, vanilla_end = (0, 0)
            install_start = 25
        if not self._download_file_with_progress(
            installer_url, installer_path, progress_callback, dl_start, dl_end, "下載安裝器...", cancel_flag
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
        try:
            process = SubprocessUtils.popen_checked(
                cmd,
                cwd=str(Path(download_path).parent),
                stdin=SubprocessUtils.DEVNULL,
                stdout=SubprocessUtils.PIPE,
                stderr=SubprocessUtils.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=SubprocessUtils.CREATE_NO_WINDOW,
            )
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
        except (SubprocessUtils.CalledProcessError, OSError) as e:
            logger.exception(f"執行安裝器時發生可預期的子程序錯誤: {e}")
            return self._fail(progress_callback, f"執行安裝器時發生錯誤: {e}", debug=f"[DEBUG] Popen exception: {e}")
        except Exception as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(installer_path),
                    reason="run_installer_failed",
                    details={"installer": installer_path, "cmd": cmd},
                )
            logger.exception(f"執行安裝器時發生錯誤: {e}")
            return self._fail(progress_callback, f"執行安裝器時發生錯誤: {e}", debug=f"[DEBUG] Popen exception: {e}")
        try:
            base_dir = Path(download_path).parent
            run_bat_path = base_dir / "run.bat"
            run_sh_path = base_dir / "run.sh"
            start_server_path = base_dir / "start_server.bat"
            installer_log_path = base_dir / "installer.log"
            java_line = None
            if run_bat_path.exists():
                try:
                    content = PathUtils.read_text_file(run_bat_path, errors="ignore")
                    if content:
                        for line in content.splitlines():
                            if re.search("\\bjava\\s+@user_jvm_args\\\\.txt\\b", line, re.IGNORECASE):
                                java_line = line.strip()
                                break
                    if java_line and "nogui" not in java_line.lower():
                        java_line += " nogui"
                except OSError as e:
                    logger.warning(f"無法讀取 run.bat (IO): {e}")
                    UIUtils.show_warning("讀取失敗", f"無法讀取 run.bat：{e}", parent=parent_window)
                except Exception as e:
                    with suppress(Exception):
                        record_and_mark(
                            e,
                            Path(run_bat_path),
                            reason="read_run_bat_unexpected",
                            details={"path": str(run_bat_path)},
                        )
                    logger.exception(f"讀取 run.bat 時發生未預期錯誤: {e}")
                    UIUtils.show_warning("讀取失敗", f"無法讀取 run.bat：{e}", parent=parent_window)
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
                    UIUtils.show_warning("修改失敗", f"無法修改 start_server.bat：{e}", parent=parent_window)
                except Exception as e:
                    with suppress(Exception):
                        record_and_mark(
                            e,
                            Path(start_server_path),
                            reason="modify_start_server_bat_unexpected",
                            details={"path": str(start_server_path)},
                        )
                    logger.exception(f"修改 start_server.bat 時發生未預期錯誤: {e}")
                    UIUtils.show_warning("修改失敗", f"無法修改 start_server.bat：{e}", parent=parent_window)
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
                UIUtils.show_warning(
                    "清理失敗", f"安裝完成，但無法清理安裝器檔案：{installer_path}\n可手動刪除。", parent=parent_window
                )
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
                UIUtils.show_warning(
                    "清理失敗", f"安裝完成，但無法清理安裝器檔案：{installer_path}\n可手動刪除。", parent=parent_window
                )
        except Exception as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(installer_path),
                    reason="installer_process_failed",
                    details={"installer": installer_path},
                )
            logger.exception(f"安裝過程中發生錯誤: {e}")
            UIUtils.show_error("安裝失敗", f"安裝過程中發生錯誤：{e}", parent=parent_window)
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
            server_url, download_path, progress_callback, 20, 100, "下載 Minecraft 伺服器...", cancel_flag
        )

    def _download_file_with_progress(
        self,
        url: str,
        dest_path: str,
        progress_callback,
        start_percent: int,
        end_percent: int,
        status_text: str,
        cancel_flag: dict | CancellationToken | None,
    ) -> bool:
        """下載檔案並顯示進度。"""

        def on_progress(downloaded, total):
            if total > 0 and progress_callback:
                percent = start_percent + downloaded / total * (end_percent - start_percent)
                progress_callback(percent, status_text)

        def check_cancel():
            if not cancel_flag:
                return False
            try:
                # 支援多種取消標記形式：CancellationToken、dict 或帶有 cancelled 屬性的物件
                if hasattr(cancel_flag, "is_cancelled") and callable(cancel_flag.is_cancelled):
                    cancelled = bool(cancel_flag.is_cancelled())
                elif isinstance(cancel_flag, dict):
                    cancelled = bool(cancel_flag.get("cancelled"))
                elif hasattr(cancel_flag, "cancelled"):
                    cancelled = bool(cancel_flag.cancelled)
                else:
                    cancelled = False
                if cancelled:
                    if progress_callback:
                        self._fail(progress_callback, "已取消下載")
                    return True
            except Exception:
                return False
            return False

        if HTTPUtils.download_file(
            url, dest_path, progress_callback=on_progress, timeout=30, cancel_check=check_cancel
        ):
            return True
        return self._fail(progress_callback, "下載失敗：無法獲取檔案")

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

    def _standardize_loader_type(self, lt: str, loader_version: str) -> str:
        """標準化載入器類型：將輸入轉為小寫並進行基本推斷。"""
        return ServerDetectionVersionUtils.standardize_loader_type(lt, loader_version)

    def _fail(self, progress_callback, user_msg: str, debug: str = "") -> bool:
        """通用失敗處理：顯示錯誤訊息並回傳 False。"""
        if debug:
            logger.debug(debug)
        if progress_callback:
            progress_callback(100, user_msg)
        return False
