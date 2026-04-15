"""伺服器檢測工具模組
提供伺服器型態、版本、啟動檔與記憶體相關偵測能力。
"""

import re
from pathlib import Path

from ...models import ServerConfig
from .. import PathUtils, ServerDetectionVersionUtils, UIUtils, get_logger

logger = get_logger().bind(component="ServerDetectionUtils")
__all__ = ["ServerDetectionUtils"]
FABRIC_JAR_NAMES = ["fabric-server-launch.jar", "fabric-server-launcher.jar"]
FORGE_LIBRARY_PATH = "libraries/net/minecraftforge/forge"


class ServerDetectionUtils:
    """伺服器檢測工具類別，提供各種伺服器相關的檢測和驗證功能"""

    @staticmethod
    def detect_loader_type(server_path: Path, jar_names: list[str]) -> str:
        """偵測載入器類型。

        Args:
            server_path: 伺服器資料夾路徑。
            jar_names: 伺服器目錄內的 JAR 檔名清單。

        Returns:
            偵測到的載入器類型。
        """
        for fabric_jar in FABRIC_JAR_NAMES:
            if (server_path / fabric_jar).exists():
                return "fabric"
        if (server_path / FORGE_LIBRARY_PATH).is_dir():
            return "forge"
        jar_names_lower = [n.lower() for n in jar_names]
        for name in jar_names_lower:
            if "fabric" in name:
                return "fabric"
            if "forge" in name:
                return "forge"
        return "vanilla"

    @staticmethod
    def find_main_jar(server_path: Path, loader_type: str, server_config=None) -> str:
        """尋找主要 JAR 檔案，根據載入器類型和伺服器配置進行優先順序檢測。

        Args:
            server_path: 伺服器資料夾路徑。
            loader_type: 載入器類型。
            server_config: 伺服器設定物件。

        Returns:
            主要 JAR 檔或啟動參照字串。
        """
        loader_type = (loader_type or "").lower()
        if loader_type == "forge":
            args_file = ServerDetectionUtils.find_forge_args_file(server_path, server_config)
            if args_file and args_file.exists():
                try:
                    relative_path = args_file.relative_to(server_path)
                    return f"@{relative_path.as_posix()}"
                except ValueError:
                    return f"@{args_file.name}"
            for jar_file in server_path.glob("*.jar"):
                if "forge" in jar_file.name.lower():
                    return jar_file.name
        elif loader_type == "fabric":
            for fabric_jar in FABRIC_JAR_NAMES:
                if (server_path / fabric_jar).exists():
                    return fabric_jar
        for jar_name in ["server.jar", "minecraft_server.jar"]:
            if (server_path / jar_name).exists():
                return jar_name
        jar_files = list(server_path.glob("*.jar"))
        if jar_files:
            return jar_files[0].name
        return "server.jar"

    @staticmethod
    def find_startup_script(server_path: Path) -> Path | None:
        """尋找伺服器啟動腳本。

        Args:
            server_path: 伺服器資料夾路徑。

        Returns:
            找到時回傳啟動腳本 Path，否則回傳 None。
        """
        script_candidates = ["start_server.bat", "run.bat", "start.bat", "server.bat"]
        for script_name in script_candidates:
            candidate_path = server_path / script_name
            if candidate_path.exists():
                return candidate_path
        return None

    @staticmethod
    def get_missing_server_files(folder_path: Path) -> list:
        """檢查伺服器資料夾中缺少的關鍵檔案清單"""
        missing = []
        if not (folder_path / "server.jar").exists() and (
            not any(
                (folder_path / f).exists()
                for f in ["minecraft_server.jar", "fabric-server-launch.jar", "fabric-server-launcher.jar"]
            )
        ):
            missing.append("server.jar 或同等主程式 JAR")
        if not (folder_path / "eula.txt").exists():
            missing.append("eula.txt")
        if not (folder_path / "server.properties").exists():
            missing.append("server.properties")
        return missing

    @staticmethod
    def detect_eula_acceptance(server_path: Path) -> bool:
        """檢測 `eula.txt` 檔案中是否已設定 `eula=true`。

        Args:
            server_path: 伺服器資料夾路徑。

        Returns:
            若已接受 EULA 則回傳 True，否則回傳 False。
        """
        eula_file = server_path / "eula.txt"
        if not eula_file.exists():
            return False
        try:
            content = PathUtils.read_text_file(eula_file, errors="ignore") or ""
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip().lower() == "eula":
                        return value.strip().lower() == "true"
            return False
        except Exception as e:
            logger.exception(f"讀取 eula.txt 失敗: {e}")
            return False

    @staticmethod
    def _process_startup_script(file_path: Path) -> tuple[str, bool, int | None, int | None]:
        """處理啟動腳本：移除 pause、添加 nogui、提取記憶體設定"""
        modified = False
        max_m = None
        min_m = None
        new_lines = []
        content = PathUtils.read_text_file(file_path, errors="ignore")
        if not content:
            return ("", False, None, None)
        for line in content.splitlines(keepends=True):
            line_stripped = line.strip().lower()
            if line_stripped in ["pause", "@pause", "pause.", "@pause."]:
                modified = True
                continue
            if "java" in line and ("-Xmx" in line or "-Xms" in line or ".jar" in line):
                from .server_memory_utils import MemoryUtils

                if "nogui" not in line.lower():
                    line = line.rstrip("\r\n") + " nogui\n"
                    modified = True
                if not max_m:
                    max_m = MemoryUtils.parse_memory_setting(line, "Xmx")
                if not min_m:
                    min_m = MemoryUtils.parse_memory_setting(line, "Xms")
            new_lines.append(line)
        return ("".join(new_lines), modified, max_m, min_m)

    @staticmethod
    def _detect_memory_from_file(file_path: Path, is_script: bool = False) -> tuple[int | None, int | None]:
        """從單個檔案偵測記憶體設定（統一接口）"""
        if not file_path.exists():
            return (None, None)
        try:
            if is_script:
                script_content, modified, max_m, min_m = ServerDetectionUtils._process_startup_script(file_path)
                if modified:
                    try:
                        PathUtils.write_text_file(file_path, script_content)
                        logger.info(f"已優化啟動腳本: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"無法更新腳本 {file_path}: {e}")
                return (max_m, min_m)
            content = PathUtils.read_text_file(file_path, errors="ignore") or ""
            from .server_memory_utils import MemoryUtils

            max_m = MemoryUtils.parse_memory_setting(content, "Xmx")
            min_m = MemoryUtils.parse_memory_setting(content, "Xms")
            return (max_m, min_m)
        except Exception as e:
            logger.debug(f"讀取記憶體檔案失敗 {file_path}: {e}")
            return (None, None)

    @staticmethod
    def update_forge_user_jvm_args(server_path: Path, config: ServerConfig) -> None:
        """更新新版 Forge 的 `user_jvm_args.txt` 檔案，設定記憶體參數。

        Args:
            server_path: 伺服器資料夾路徑。
            config: 伺服器設定物件。
        """
        user_jvm_args_path = server_path / "user_jvm_args.txt"
        lines = []
        if config.memory_min_mb:
            lines.append(f"-Xms{config.memory_min_mb}M\n")
        if config.memory_max_mb:
            lines.append(f"-Xmx{config.memory_max_mb}M\n")
        try:
            PathUtils.write_text_file(user_jvm_args_path, "".join(lines))
        except Exception as e:
            logger.exception(f"寫入失敗: {e}")
            UIUtils.show_error("寫入失敗", f"無法更新 {user_jvm_args_path} 檔案。請檢查權限或磁碟空間。錯誤: {e}")

    @staticmethod
    def detect_memory_from_sources(server_path: Path, config: ServerConfig) -> None:
        """從多個來源檢測記憶體設定。

        Args:
            server_path: 伺服器資料夾路徑。
            config: 伺服器設定物件。
        """
        memory_sources = [
            [("user_jvm_args.txt", False), ("jvm.args", False)],
            [("start_server.bat", True), ("start.bat", True)],
        ]
        max_mem = None
        min_mem = None
        for source_group in memory_sources:
            for source_file, is_script in source_group:
                fpath = server_path / source_file
                max_m, min_m = ServerDetectionUtils._detect_memory_from_file(fpath, is_script)
                if max_m is not None:
                    max_mem = max_m
                if min_m is not None:
                    min_mem = min_m
                if max_mem is not None and min_mem is not None:
                    logger.debug(f"從 {source_file} 偵測到記憶體: {min_mem}M - {max_mem}M")
                    break
            if max_mem is not None and min_mem is not None:
                break
        if max_mem is None or min_mem is None:
            for script in server_path.glob("*.bat"):
                if script.name in ["start_server.bat", "start.bat"]:
                    continue
                max_m, min_m = ServerDetectionUtils._detect_memory_from_file(script, is_script=True)
                if max_m:
                    max_mem = max_mem or max_m
                if min_m:
                    min_mem = min_mem or min_m
                if max_mem and min_mem:
                    break
        if max_mem is not None:
            config.memory_max_mb = max_mem
            config.memory_min_mb = min_mem if min_mem is not None else None
        elif min_mem is not None:
            config.memory_max_mb = min_mem
            config.memory_min_mb = min_mem
        if hasattr(config, "loader_type") and str(getattr(config, "loader_type", "")).lower() == "forge":
            ServerDetectionUtils.update_forge_user_jvm_args(server_path, config)

    @staticmethod
    def detect_server_type(server_path: Path, config: ServerConfig, print_result: bool = True) -> None:
        """檢測伺服器類型和版本。

        Args:
            server_path: 伺服器資料夾路徑。
            config: 伺服器設定物件。
            print_result: 是否輸出偵測結果日誌。
        """
        try:
            jar_files = list(server_path.glob("*.jar"))
            jar_names = [f.name for f in jar_files]
            detection_source = {}
            detected_loader = ServerDetectionUtils.detect_loader_type(server_path, jar_names)
            config.loader_type = detected_loader
            if detected_loader == "fabric":
                detected_file = next((f for f in FABRIC_JAR_NAMES if (server_path / f).exists()), None)
                detection_source["loader_type"] = f"檔案 {detected_file}" if detected_file else "Fabric 檔案"
            elif detected_loader == "forge":
                if (server_path / FORGE_LIBRARY_PATH).is_dir():
                    detection_source["loader_type"] = f"目錄 {FORGE_LIBRARY_PATH}"
                else:
                    detected_file = next((name for name in jar_names if "forge" in name.lower()), None)
                    detection_source["loader_type"] = f"JAR 檔案 {detected_file}" if detected_file else "Forge JAR"
            elif detected_loader == "vanilla":
                detected_file = next(
                    (name for name in jar_names if name.lower() in ("server.jar", "minecraft_server.jar")), None
                )
                detection_source["loader_type"] = f"JAR 檔案 {detected_file}" if detected_file else "Vanilla JAR"
            else:
                detection_source["loader_type"] = "無法判斷"
            ServerDetectionUtils.detect_loader_and_version_from_sources(
                server_path, config, config.loader_type, detection_source
            )
            ServerDetectionUtils.detect_memory_from_sources(server_path, config)
            detected_main_jar = ServerDetectionUtils.find_main_jar(server_path, config.loader_type, config)
            config.eula_accepted = ServerDetectionUtils.detect_eula_acceptance(server_path)
            if print_result:
                logger.info(f"偵測結果 - 路徑: {server_path.name}")
                logger.info(f"  載入器: {config.loader_type} (來源: {detection_source.get('loader_type', '未知')})")
                if detection_source.get("mc_version"):
                    logger.info(f"  MC版本: {config.minecraft_version} (來源: {detection_source['mc_version']})")
                else:
                    logger.info(f"  MC版本: {config.minecraft_version}")
                if detection_source.get("loader_version"):
                    logger.info(f"  載入器版本: {config.loader_version} (來源: {detection_source['loader_version']})")
                logger.info(f"  主要JAR/啟動檔: {detected_main_jar}")
                logger.info(f"  EULA狀態: {('已接受' if config.eula_accepted else '未接受')}")
                if hasattr(config, "memory_max_mb") and config.memory_max_mb:
                    if hasattr(config, "memory_min_mb") and config.memory_min_mb:
                        logger.info(f"  記憶體: 最小 {config.memory_min_mb}MB, 最大 {config.memory_max_mb}MB")
                    else:
                        logger.info(f"  記憶體: 0-{config.memory_max_mb}MB")
                else:
                    logger.info("  記憶體: 未設定")
        except Exception as e:
            logger.exception(f"檢測伺服器類型失敗: {e}")

    @staticmethod
    def is_valid_server_folder(folder_path: Path) -> bool:
        """檢查是否為有效的 Minecraft 伺服器資料夾。

        Args:
            folder_path: 待檢查的資料夾路徑。

        Returns:
            若為有效的伺服器資料夾則回傳 True，否則回傳 False。
        """
        if not folder_path.is_dir():
            return False
        server_jars = ["server.jar", "minecraft_server.jar", "fabric-server-launch.jar", "fabric-server-launcher.jar"]
        if any((folder_path / jar_name).exists() for jar_name in server_jars):
            return True
        for file in folder_path.glob("*.jar"):
            jar_name = file.name.lower()
            if any(pattern in jar_name for pattern in ["forge", "server", "minecraft"]):
                return True
        server_indicators = ["server.properties", "eula.txt"]
        return bool(any((folder_path / indicator).exists() for indicator in server_indicators))

    @staticmethod
    def _get_latest_log_file(server_path: Path) -> Path | None:
        """取得最新的日誌檔，優先級: 時間戳 > 標準名稱"""
        log_candidates = ["latest.log", "server.log", "debug.log"]
        logs_dir = server_path / "logs"
        if not logs_dir.is_dir():
            return None
        found_logs = []
        for name in log_candidates:
            fpath = logs_dir / name
            if fpath.exists():
                found_logs.append(fpath)
        if not found_logs:
            found_logs = list(logs_dir.glob("*.log"))
        if not found_logs:
            return None
        found_logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        logger.debug(f"選擇日誌檔: {found_logs[0].name}")
        return found_logs[0]

    @staticmethod
    def detect_loader_and_version_from_sources(
        server_path: Path, config, loader: str, detection_source: dict | None = None
    ) -> None:
        """從多種來源偵測 Fabric/Forge 載入器與 Minecraft 版本。

        Args:
            server_path: 伺服器資料夾路徑。
            config: 伺服器設定物件。
            loader: 已知的載入器類型。
            detection_source: 用來記錄偵測來源的字典。
        """
        if detection_source is None:
            detection_source = {}

        def is_unknown(value: str | None) -> bool:
            return value in (None, "", "unknown", "Unknown", "無")

        def set_if_unknown(attr_name: str, value: str):
            if is_unknown(getattr(config, attr_name)):
                setattr(config, attr_name, value)

        def first_match(content: str, patterns: list[str]) -> str | None:
            for pat in patterns:
                m = re.search(pat, content, re.IGNORECASE)
                if m:
                    return m.group(1)
            return None

        def detect_from_logs():
            """從日誌檔偵測載入器和 Minecraft 版本 - 改進版本"""
            log_file = ServerDetectionUtils._get_latest_log_file(server_path)
            if not log_file or not log_file.exists():
                return
            loader_patterns = {
                "fabric": [
                    "Fabric Loader (\\d+\\.\\d+\\.\\d+)",
                    "FabricLoader/(\\d+\\.\\d+\\.\\d+)",
                    "fabric-loader (\\d+\\.\\d+\\.\\d+)",
                    "Loading Fabric (\\d+\\.\\d+\\.\\d+)",
                ],
                "forge": [
                    "fml.forgeVersion, (\\d+\\.\\d+\\.\\d+)",
                    "Forge Mod Loader version (\\d+\\.\\d+\\.\\d+)",
                    "MinecraftForge v(\\d+\\.\\d+\\.\\d+)",
                    "Forge (\\d+\\.\\d+\\.\\d+)",
                    "forge-(\\d+\\.\\d+\\.\\d+)",
                ],
            }
            mc_patterns = [
                "Starting minecraft server version (\\d+\\.\\d+(?:\\.\\d+)?)",
                "Minecraft (\\d+\\.\\d+(?:\\.\\d+)?)",
                "Server version: (\\d+\\.\\d+(?:\\.\\d+)?)",
            ]
            try:
                content = PathUtils.read_text_file(log_file, errors="ignore")
                if content:
                    lines = content.splitlines(keepends=True)[:2000]
                    content = "".join(lines)
                else:
                    return
            except Exception as e:
                logger.debug(f"讀取日誌檔失敗 {log_file}: {e}")
                return
            if loader in loader_patterns:
                v = first_match(content, loader_patterns[loader])
                if v:
                    set_if_unknown("loader_version", v)
                    if detection_source:
                        detection_source["loader_version"] = f"日誌檔 {log_file.name}"
            mc_ver = first_match(content, mc_patterns)
            if mc_ver:
                set_if_unknown("minecraft_version", mc_ver)
                if detection_source and "mc_version" not in detection_source:
                    detection_source["mc_version"] = f"日誌檔 {log_file.name}"

        def detect_from_forge_lib():
            forge_dir = server_path / "libraries" / "net" / "minecraftforge" / "forge"
            if not forge_dir.is_dir():
                return
            subdirs = [d for d in forge_dir.iterdir() if d.is_dir()]
            if not subdirs:
                return
            folder = subdirs[0].name
            mc, forge_ver = ServerDetectionVersionUtils.extract_version_from_forge_path(folder)
            if mc and forge_ver:
                set_if_unknown("minecraft_version", mc)
                set_if_unknown("loader_version", forge_ver)
            else:
                for jar in subdirs[0].glob("*.jar"):
                    m2 = re.match("forge-(\\d+\\.\\d+(?:\\.\\d+)?)-(\\d+\\.\\d+(?:\\.\\d+)?)-.*\\.jar", jar.name)
                    if m2:
                        mc2, forge_ver2 = m2.groups()
                        set_if_unknown("minecraft_version", mc2)
                        set_if_unknown("loader_version", forge_ver2)
                        break

        def detect_from_jars():
            for jar in server_path.glob("*.jar"):
                name_lower = jar.name.lower()
                if is_unknown(config.loader_type):
                    if "fabric" in name_lower:
                        config.loader_type = "fabric"
                    elif "forge" in name_lower:
                        config.loader_type = "forge"
                    elif name_lower in {"server.jar", "minecraft_server.jar"}:
                        config.loader_type = "vanilla"
                m = re.search("forge-(\\d+\\.\\d+(?:\\.\\d+)?)-(\\d+\\.\\d+(?:\\.\\d+)?).*\\.jar", jar.name)
                if m:
                    mc, forge_ver = m.groups()
                    set_if_unknown("minecraft_version", mc)
                    set_if_unknown("loader_version", forge_ver)
                if (
                    not is_unknown(config.loader_type)
                    and (not is_unknown(config.loader_version))
                    and (not is_unknown(config.minecraft_version))
                ):
                    break

        def detect_from_version_json():
            fp = server_path / "version.json"
            data = PathUtils.load_json(fp)
            if not data:
                return
            if "id" in data:
                set_if_unknown("minecraft_version", data["id"])
            if "forgeVersion" in data:
                set_if_unknown("loader_version", data["forgeVersion"])

        detect_from_logs()
        if loader == "fabric" and is_unknown(config.loader_version):
            config.loader_version = "unknown"
        if loader == "forge":
            detect_from_forge_lib()
        detect_from_jars()
        detect_from_version_json()
        if is_unknown(config.loader_type) and is_unknown(config.loader_version):
            config.loader_type = "unknown"

    @staticmethod
    def find_forge_args_file(server_path: Path, server_config=None) -> Path | None:
        """尋找 Forge 的 `win_args.txt` 啟動參數檔。

        Args:
            server_path: 伺服器資料夾路徑。
            server_config: 伺服器設定物件。

        Returns:
            找到時回傳參數檔 Path，否則回傳 None。
        """
        forge_lib_dir = server_path / "libraries" / "net" / "minecraftforge" / "forge"
        if not forge_lib_dir.is_dir():
            return None
        if (
            server_config
            and server_config.minecraft_version
            and server_config.loader_version
            and (server_config.minecraft_version.lower() != "unknown")
            and (server_config.loader_version.lower() != "unknown")
        ):
            folder_name = f"{server_config.minecraft_version}-{server_config.loader_version}"
            args_path = forge_lib_dir / folder_name / "win_args.txt"
            if args_path.exists():
                return args_path
        arg_files = list(forge_lib_dir.rglob("win_args.txt"))
        if arg_files:
            arg_files.sort(key=lambda p: len(p.parts), reverse=True)
            return arg_files[0]
        return None

    @staticmethod
    def _parse_forge_args_file(args_path: Path) -> dict[str, str | list[str] | None]:
        """包含以下可能的鍵值對："""
        result: dict[str, str | list[str] | None] = {
            "jar": None,
            "bootstraplauncher": None,
            "forge_libraries": [],
            "minecraft_version": None,
            "forge_version": None,
        }
        try:
            content = PathUtils.read_text_file(args_path, errors="ignore") or ""
            jar_match = re.search("-jar\\s+([^\\s]+\\.jar)", content, re.IGNORECASE)
            if jar_match:
                result["jar"] = jar_match.group(1)
                logger.info(f"偵測到 Modern Forge -jar 格式: {result['jar']}")
            bootstrap_match = re.search("cpw\\.mods\\.bootstraplauncher\\.BootstrapLauncher", content, re.IGNORECASE)
            if bootstrap_match:
                result["bootstraplauncher"] = "cpw.mods.bootstraplauncher.BootstrapLauncher"
                logger.info("偵測到 BootstrapLauncher 格式 (1.20.1 類型)")
            forge_libs = re.findall(
                "libraries[\\\\/].*?(?:forge|fmlloader|minecraft[/\\\\]server).*?\\.jar", content, re.IGNORECASE
            )
            if forge_libs:
                forge_libs_list: list[str] = list(set(forge_libs))
                result["forge_libraries"] = forge_libs_list
                logger.debug(f"找到 {len(forge_libs_list)} 個 Forge libraries")
            parent_dir = args_path.parents[0].name
            mc_ver, forge_ver = ServerDetectionVersionUtils.extract_version_from_forge_path(parent_dir)
            if mc_ver and forge_ver:
                result["minecraft_version"] = mc_ver
                result["forge_version"] = forge_ver
                logger.info(f"從 Forge 目錄路徑提取版本: MC={mc_ver}, Forge={forge_ver}")
        except Exception as e:
            logger.warning(f"解析 win_args.txt 失敗: {e}")
        return result
