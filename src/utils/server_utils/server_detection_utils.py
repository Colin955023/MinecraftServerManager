"""
伺服器檢測工具模組
提供伺服器型態、版本、啟動檔與記憶體相關偵測能力
"""

from __future__ import annotations

import re
import zipfile
from functools import lru_cache
from pathlib import Path

import orjson

from src.models import ServerConfig
from src.utils import PathUtils, get_logger, parse_version_safe

logger = get_logger().bind(component="ServerDetectionUtils")

MANAGED_STARTUP_SCRIPT_NAME = "start_server.bat"
STARTUP_SCRIPT_CANDIDATES = (
    MANAGED_STARTUP_SCRIPT_NAME,
    "run.bat",
    "start.bat",
    "server.bat",
)

FABRIC_JAR_NAMES = ("fabric-server-launch.jar", "fabric-server-launcher.jar")
QUILT_JAR_NAMES = ("quilt-server-launch.jar", "quilt-server-launcher.jar")
FORGE_LIBRARY_PATH = "libraries/net/minecraftforge/forge"
NEOFORGE_LIBRARY_PATH = "libraries/net/neoforged/neoforge"
QUILT_LIBRARY_PATH = "libraries/org/quiltmc"
FABRIC_LIBRARY_PATH = "libraries/net/fabricmc"
SERVER_JAR_CANDIDATES = (
    "server.jar",
    "minecraft_server.jar",
    *FABRIC_JAR_NAMES,
    *QUILT_JAR_NAMES,
)


class ServerDetectionUtils:
    """伺服器檢測工具類別，提供各種伺服器相關的檢測和驗證功能"""

    @staticmethod
    def _extract_mc_version_from_jar_file(jar_path: Path) -> str | None:
        """從伺服器 JAR 內的版本 metadata 讀取 Minecraft 版本"""
        try:
            with zipfile.ZipFile(jar_path) as jar_file:
                names = set(jar_file.namelist())
                if "version.json" in names:
                    with jar_file.open("version.json") as version_file:
                        payload = orjson.loads(version_file.read())
                    if isinstance(payload, dict):
                        for key in ("id", "name", "release_target"):
                            detected = ServerDetectionVersionUtils.extract_mc_version_from_text(
                                str(payload.get(key, ""))
                            )
                            if detected:
                                return detected
                if "META-INF/MANIFEST.MF" in names:
                    with jar_file.open("META-INF/MANIFEST.MF") as manifest_file:
                        manifest = manifest_file.read().decode("utf-8", errors="replace")
                    return ServerDetectionVersionUtils.extract_mc_version_from_text(manifest)
        except (OSError, zipfile.BadZipFile, orjson.JSONDecodeError) as e:
            logger.debug(f"讀取 JAR 版本 metadata 失敗 {jar_path}: {e}")
        return None

    @staticmethod
    def _find_loader_args_file(server_path: Path, library_path: str, server_config=None) -> Path | None:
        loader_lib_dir = server_path / library_path
        if not loader_lib_dir.is_dir():
            return None
        if (
            server_config
            and server_config.minecraft_version
            and server_config.loader_version
            and (server_config.minecraft_version.lower() != "unknown")
            and (server_config.loader_version.lower() != "unknown")
        ):
            folder_name = f"{server_config.minecraft_version}-{server_config.loader_version}"
            args_path = loader_lib_dir / folder_name / "win_args.txt"
            if args_path.exists():
                return args_path
        arg_files = list(loader_lib_dir.rglob("win_args.txt"))
        if arg_files:
            arg_files.sort(key=lambda p: len(p.parts), reverse=True)
            return arg_files[0]
        return None

    @staticmethod
    def detect_loader_type(server_path: Path, jar_names: list[str]) -> str:
        """
        偵測載入器類型

        Args:
            server_path: 伺服器資料夾路徑
            jar_names: 伺服器目錄內的 JAR 檔名清單

        Returns:
            偵測到的載入器類型
        """
        for fabric_jar in FABRIC_JAR_NAMES:
            if (server_path / fabric_jar).exists():
                return "fabric"
        for quilt_jar in QUILT_JAR_NAMES:
            if (server_path / quilt_jar).exists():
                return "quilt"
        if (server_path / QUILT_LIBRARY_PATH).is_dir():
            return "quilt"
        if (server_path / NEOFORGE_LIBRARY_PATH).is_dir() or (server_path / "libraries/net/neoforged").is_dir():
            return "neoforge"
        if (server_path / FORGE_LIBRARY_PATH).is_dir() or (server_path / "libraries/net/minecraftforge").is_dir():
            return "forge"
        if (server_path / FABRIC_LIBRARY_PATH).is_dir():
            return "fabric"
        jar_names_lower = [n.lower() for n in jar_names]
        for name in jar_names_lower:
            if "neoforge" in name.replace("-", "").replace("_", ""):
                return "neoforge"
            if "forge" in name and "neo" not in name:
                return "forge"
            if "quilt" in name:
                return "quilt"
            if "fabric" in name:
                return "fabric"
        return "vanilla"

    @staticmethod
    def find_main_jar(server_path: Path, loader_type: str, server_config=None) -> str:
        """
        尋找主要 JAR 檔案，根據載入器類型和伺服器設定進行優先順序檢測

        Args:
            server_path: 伺服器資料夾路徑
            loader_type: 載入器類型
            server_config: 伺服器設定物件

        Returns:
            主要 JAR 檔或啟動參照字串
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
                if "forge" in jar_file.name.lower() and "neo" not in jar_file.name.lower():
                    return jar_file.name
        elif loader_type == "neoforge":
            args_file = ServerDetectionUtils.find_neoforge_args_file(server_path, server_config)
            if args_file and args_file.exists():
                try:
                    relative_path = args_file.relative_to(server_path)
                    return f"@{relative_path.as_posix()}"
                except ValueError:
                    return f"@{args_file.name}"
            for jar_file in server_path.glob("*.jar"):
                if "neoforge" in jar_file.name.lower().replace("-", "").replace("_", ""):
                    return jar_file.name
        elif loader_type == "fabric":
            for fabric_jar in FABRIC_JAR_NAMES:
                if (server_path / fabric_jar).exists():
                    return fabric_jar
        elif loader_type == "quilt":
            for quilt_jar in QUILT_JAR_NAMES:
                if (server_path / quilt_jar).exists():
                    return quilt_jar
        for jar_name in ["server.jar", "minecraft_server.jar"]:
            if (server_path / jar_name).exists():
                return jar_name
        jar_files = list(server_path.glob("*.jar"))
        return jar_files[0].name if jar_files else "server.jar"

    @staticmethod
    def get_expected_main_jar(loader_type: str, mc_version: str | None = None) -> str:
        """
        取得預期的主要 JAR 檔案名稱 (用於預覽指令，不需實際存在的檔案)

        Args:
            loader_type: 載入器類型
            mc_version: Minecraft 版本 (可選)

        Returns:
            預期的主要 JAR 檔案名稱或啟動參照字串
        """
        loader_type = (loader_type or "").lower()
        if loader_type == "forge":
            if mc_version and (mc_version.startswith(("1.17", "1.18", "1.19", "1.2"))):
                return "@libraries/net/minecraftforge/forge/win_args.txt"
            return "forge-server.jar"
        if loader_type == "neoforge":
            return "@libraries/net/neoforged/neoforge/win_args.txt"
        if loader_type == "fabric":
            return "fabric-server-launch.jar"
        if loader_type == "quilt":
            return "quilt-server-launch.jar"
        return "server.jar"

    @staticmethod
    def find_startup_script(server_path: Path) -> Path | None:
        """
        尋找伺服器啟動腳本

        Args:
            server_path: 伺服器資料夾路徑

        Returns:
            找到時回傳啟動腳本 Path，否則回傳 None
        """
        for script_name in STARTUP_SCRIPT_CANDIDATES:
            candidate_path = server_path / script_name
            if candidate_path.exists():
                return candidate_path
        return None

    @staticmethod
    def get_missing_server_files(folder_path: Path) -> list:
        """
        檢查伺服器資料夾中缺少的關鍵檔案清單

        Args:
            folder_path: 伺服器資料夾路徑

        Returns:
            缺少的檔案名稱清單
        """
        missing = []
        if not (folder_path / "server.jar").exists() and (
            not any((folder_path / f).exists() for f in SERVER_JAR_CANDIDATES)
        ):
            missing.append("server.jar 或同等主程式 JAR")
        if not (folder_path / "eula.txt").exists():
            missing.append("eula.txt")
        if not (folder_path / "server.properties").exists():
            missing.append("server.properties")
        return missing

    @staticmethod
    def detect_eula_acceptance(server_path: Path) -> bool:
        """
        檢測 eula.txt 檔案中是否已設定 eula=true

        Args:
            server_path: 伺服器資料夾路徑

        Returns:
            若已接受 EULA 則回傳 True，否則回傳 False
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
    def update_forge_user_jvm_args(server_path: Path, config: ServerConfig) -> None:
        """
        更新新版 Forge 的 user_jvm_args.txt 檔案，設定記憶體參數

        Args:
            server_path: 伺服器資料夾路徑
            config: 伺服器設定物件
        """
        from src.utils import JvmOptionPolicy

        user_jvm_args_path = server_path / "user_jvm_args.txt"
        lines: list[str] = []
        custom_jvm_args = JvmOptionPolicy.normalize_jvm_args(getattr(config, "jvm_args", []))
        java_major = getattr(config, "java_major", None) or getattr(config, "java_major_version", None)
        loader_type = str(getattr(config, "loader_type", "") or "")
        lines.extend(
            f"{arg}\n"
            for arg in JvmOptionPolicy.recommend_gc_args(
                memory_max_mb=int(config.memory_max_mb or 0),
                java_major=int(java_major) if java_major else None,
                loader_type=loader_type,
                existing_args=custom_jvm_args,
            )
        )
        lines.extend(f"{arg}\n" for arg in custom_jvm_args)
        if config.memory_min_mb:
            lines.append(f"-Xms{config.memory_min_mb}M\n")
        if config.memory_max_mb:
            lines.append(f"-Xmx{config.memory_max_mb}M\n")
        if not PathUtils.write_text_file(user_jvm_args_path, "".join(lines)):
            logger.error(f"無法更新 {user_jvm_args_path} 檔案，請檢查權限或磁碟空間")

    @staticmethod
    def is_valid_server_folder(folder_path: Path) -> bool:
        """
        檢查是否為有效的 Minecraft 伺服器資料夾

        Args:
            folder_path: 待檢查的資料夾路徑

        Returns:
            若為有效的伺服器資料夾則回傳 True，否則回傳 False
        """
        if not folder_path.is_dir():
            return False
        if any((folder_path / jar_name).exists() for jar_name in SERVER_JAR_CANDIDATES):
            return True
        for file in folder_path.glob("*.jar"):
            jar_name = file.name.lower()
            if any(pattern in jar_name for pattern in ["forge", "neoforge", "server", "minecraft"]):
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
        """
        從多種來源偵測 Fabric/Forge 載入器與 Minecraft 版本

        Args:
            server_path: 伺服器資料夾路徑
            config: 伺服器設定物件
            loader: 已知的載入器類型
            detection_source: 用來記錄偵測來源的字典
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
                "quilt": [
                    "Quilt Loader (\\d+\\.\\d+\\.\\d+)",
                    "QuiltLoader/(\\d+\\.\\d+\\.\\d+)",
                    "quilt-loader (\\d+\\.\\d+\\.\\d+)",
                    "Loading Quilt (\\d+\\.\\d+\\.\\d+)",
                ],
                "neoforge": [
                    "NeoForge version (\\d+\\.\\d+\\.\\d+)",
                    "NeoForge v(\\d+\\.\\d+\\.\\d+)",
                    "NeoForge (\\d+\\.\\d+\\.\\d+)",
                    "neoforge-(\\d+\\.\\d+\\.\\d+)",
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

        def detect_from_jar_metadata():
            preferred_names = ["server.jar", "minecraft_server.jar"]
            preferred_jars = [server_path / name for name in preferred_names if (server_path / name).exists()]
            other_jars = [
                jar
                for jar in server_path.glob("*.jar")
                if jar not in preferred_jars and "installer" not in jar.name.lower()
            ]
            for jar in [*preferred_jars, *other_jars]:
                mc_ver = ServerDetectionUtils._extract_mc_version_from_jar_file(jar)
                if mc_ver:
                    set_if_unknown("minecraft_version", mc_ver)
                    if detection_source and "mc_version" not in detection_source:
                        detection_source["mc_version"] = f"JAR metadata {jar.name}"
                    return

        def detect_from_version_json():
            fp = server_path / "version.json"
            data = PathUtils.load_json(fp)
            if not data:
                return
            if "id" in data:
                set_if_unknown("minecraft_version", data["id"])
            if "forgeVersion" in data:
                set_if_unknown("loader_version", data["forgeVersion"])

        def detect_from_fabric_lib():
            fabric_dir = server_path / "libraries" / "net" / "fabricmc" / "fabric-loader"
            if not fabric_dir.is_dir():
                return
            subdirs = [d for d in fabric_dir.iterdir() if d.is_dir()]
            if not subdirs:
                return
            subdirs.sort(key=lambda d: d.name, reverse=True)
            set_if_unknown("loader_version", subdirs[0].name)
            if detection_source:
                detection_source["loader_version"] = "Fabric 函式庫目錄"

        def detect_from_quilt_lib():
            quilt_dir = server_path / "libraries" / "org" / "quiltmc" / "quilt-loader"
            if not quilt_dir.is_dir():
                return
            subdirs = [d for d in quilt_dir.iterdir() if d.is_dir()]
            if not subdirs:
                return
            subdirs.sort(key=lambda d: d.name, reverse=True)
            set_if_unknown("loader_version", subdirs[0].name)
            if detection_source:
                detection_source["loader_version"] = "Quilt 函式庫目錄"

        def detect_from_neoforge_lib():
            neoforge_dir = server_path / "libraries" / "net" / "neoforged" / "neoforge"
            if not neoforge_dir.is_dir():
                return
            subdirs = [d for d in neoforge_dir.iterdir() if d.is_dir()]
            if not subdirs:
                return
            subdirs.sort(key=lambda d: d.name, reverse=True)
            folder = subdirs[0].name
            set_if_unknown("loader_version", folder)
            if detection_source:
                detection_source["loader_version"] = "NeoForge 函式庫目錄"
            m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", folder)
            if m:
                major, minor, _patch = m.groups()
                mc_ver = f"1.{major}.{minor}" if minor else f"1.{major}"
                set_if_unknown("minecraft_version", mc_ver)
                if detection_source and "mc_version" not in detection_source:
                    detection_source["mc_version"] = "NeoForge 函式庫版本推導"

        detect_from_logs()
        if loader == "fabric":
            detect_from_fabric_lib()
        elif loader == "quilt":
            detect_from_quilt_lib()
        elif loader == "neoforge":
            detect_from_neoforge_lib()
        elif loader == "forge":
            detect_from_forge_lib()
        detect_from_jars()
        detect_from_jar_metadata()
        detect_from_version_json()
        if str(getattr(config, "loader_type", "")).lower() == "vanilla" and not is_unknown(
            getattr(config, "minecraft_version", "")
        ):
            config.loader_version = config.minecraft_version
        if is_unknown(config.loader_type) and is_unknown(config.loader_version):
            config.loader_type = "unknown"

    @staticmethod
    def find_forge_args_file(server_path: Path, server_config=None) -> Path | None:
        """
        尋找 Forge 的 win_args.txt 啟動參數檔

        Args:
            server_path: 伺服器資料夾路徑
            server_config: 伺服器設定物件

        Returns:
            找到時回傳參數檔 Path，否則回傳 None
        """
        return ServerDetectionUtils._find_loader_args_file(
            server_path,
            FORGE_LIBRARY_PATH,
            server_config,
        )

    @staticmethod
    def find_neoforge_args_file(server_path: Path, server_config=None) -> Path | None:
        """
        尋找 NeoForge 的 win_args.txt 啟動參數檔

        Args:
            server_path: 伺服器資料夾路徑
            server_config: 伺服器設定物件

        Returns:
            找到時回傳參數檔 Path，否則回傳 None
        """
        return ServerDetectionUtils._find_loader_args_file(
            server_path,
            NEOFORGE_LIBRARY_PATH,
            server_config,
        )


class ServerDetectionVersionUtils:
    """版本與載入器文字解析工具"""

    @staticmethod
    def parse_mc_version(version_str: str) -> list[int]:
        """
        解析 Minecraft 版本字串為數字列表

        Args:
            version_str: 原始版本字串

        Returns:
            版本數字列表，例如 [1, 20, 1]
        """
        if not version_str or not isinstance(version_str, str):
            logger.debug(f"無效的 MC 版本字串: {version_str!r}")
            return []
        parsed = parse_version_safe(version_str)
        if parsed is not None and parsed.release:
            return [int(part) for part in parsed.release]
        try:
            matches = re.findall("\\d+", version_str)
            return [int(x) for x in matches] if matches else []
        except Exception as e:
            logger.exception(f"解析 MC 版本時發生錯誤: {e}")
            return []

    @staticmethod
    def is_fabric_compatible_version(mc_version: str) -> bool:
        """
        檢查 MC 版本是否與 Fabric 相容（1.14+）

        Args:
            mc_version: Minecraft 版本字串

        Returns:
            若版本與 Fabric 相容則回傳 True，否則回傳 False
        """
        try:
            parsed = parse_version_safe(mc_version)
            if parsed is not None:
                return parsed.release >= (1, 14)
            version_parts = ServerDetectionVersionUtils.parse_mc_version(mc_version)
            if not version_parts:
                return False
            major = version_parts[0]
            minor = version_parts[1] if len(version_parts) > 1 else 0
            return bool(major > 1 or (major == 1 and minor >= 14))
        except Exception as e:
            logger.exception(f"檢查 Fabric 相容性時發生錯誤: {e}")
            return False

    @staticmethod
    def standardize_loader_type(loader_type: str, loader_version: str = "") -> str:
        """
        標準化載入器類型：將輸入轉為小寫並進行基本推斷

        Args:
            loader_type: 原始載入器類型
            loader_version: 原始載入器版本字串

        Returns:
            標準化後的載入器類型
        """
        lt_low = loader_type.lower()
        if lt_low in ["fabric", "forge", "quilt", "neoforge", "vanilla", "原版"]:
            return "vanilla" if lt_low in ["vanilla", "原版"] else lt_low
        if lt_low in ["unknown", "未知"]:
            if loader_version and loader_version.replace(".", "").isdigit():
                return "forge"
            if loader_version and "fabric" in loader_version.lower():
                return "fabric"
            if loader_version and "quilt" in loader_version.lower():
                return "quilt"
            if loader_version and "neoforge" in loader_version.lower():
                return "neoforge"
            return "unknown"
        if "vanilla" in lt_low or "official" in lt_low:
            return "vanilla"
        return "unknown"

    @staticmethod
    def normalize_mc_version(mc_version) -> str:
        """
        標準化 Minecraft 版本字串

        Args:
            mc_version: 原始 Minecraft 版本值

        Returns:
            標準化後的 Minecraft 版本字串
        """
        if isinstance(mc_version, list) and mc_version:
            mc_version = str(mc_version[0])
        if isinstance(mc_version, str) and mc_version.startswith(("[", "(")):
            m = re.search("(\\d+\\.\\d+)", mc_version)
            if m:
                mc_version = m.group(1)
        return mc_version

    @staticmethod
    def clean_version(version: str) -> str:
        """
        清理版本字串中的常見後綴

        Args:
            version: 原始版本字串

        Returns:
            清理後的版本字串
        """
        if not version or version == "未知":
            return version
        cleaned = re.split(
            "[+]|-mc|-fabric|-forge|-kotlin|-api|-universal|-common|-b[0-9]*|-beta|-alpha|-snapshot",
            version,
            flags=re.IGNORECASE,
        )[0]
        cleaned = re.sub("[^\\w\\d.]+$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def extract_mc_version_from_text(text: str) -> str | None:
        """
        從文字中擷取 Minecraft 版本

        Args:
            text: 待分析的文字內容

        Returns:
            找到時回傳版本字串，否則回傳 None
        """
        if not text:
            return None
        patterns = [
            ("minecraft[:\\s]+([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)", 1),
            ("mc[:\\s]+([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)", 1),
            ("version[:\\s]+([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)", 1),
            ("\\b([0-9]+\\.[0-9]+(?:\\.[0-9]+)?-(?:pre|rc)[0-9]+)\\b", 2),
            ("\\b([0-9]+\\.[0-9]+-snapshot-[0-9]+)\\b", 3),
            ("\\b(2[0-9]w[0-9]{1,2}[a-z])\\b", 3),
            ("\\b([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)\\b", 4),
        ]
        matches = []
        for pattern, priority in patterns:
            found = re.search(pattern, text, re.IGNORECASE)
            if found:
                matches.append((found.group(1), priority))
        if matches:
            matches.sort(key=lambda item: item[1])
            return matches[0][0]
        return None

    @staticmethod
    @lru_cache(maxsize=128)
    def detect_loader_from_text(text: str) -> str:
        """
        從文字中偵測載入器類型

        Args:
            text: 待分析的文字內容

        Returns:
            偵測到的載入器類型，找不到時回傳 unknown
        """
        if not text:
            return "unknown"
        text_lower = text.lower()
        if re.search("\\bvanilla\\b|\\bofficial\\b|\\bminecraft server\\b", text_lower):
            return "vanilla"
        if re.search("\\bfabric\\b", text_lower):
            return "fabric"
        if re.search("\\bneoforge\\b", text_lower):
            return "neoforge"
        if re.search("\\bforge\\b", text_lower):
            return "forge"
        if re.search("\\bquilt\\b", text_lower):
            return "quilt"
        return "unknown"

    @staticmethod
    @lru_cache(maxsize=128)
    def extract_version_from_forge_path(path_str: str) -> tuple[str | None, str | None]:
        """
        從 Forge 路徑字串擷取 (minecraft_version, forge_version)

        Args:
            path_str: Forge 路徑或檔名字串

        Returns:
            (Minecraft 版本, Forge 版本)，無法解析時回傳 (None, None)
        """
        if not path_str:
            return (None, None)
        clean_str = path_str
        if clean_str.endswith(".jar"):
            clean_str = clean_str[:-4]
        if clean_str.startswith("forge-"):
            clean_str = clean_str[6:]
        patterns = [
            "^(\\d+\\.\\d+(?:\\.\\d+)?)-(\\d+\\.\\d+(?:\\.\\d+)?(?:\\.\\d+)?)$",
            "^(\\d+\\.\\d+(?:\\.\\d+)?)-(\\d+\\.\\d+(?:\\.\\d+)?(?:\\.\\d+)?)-.*$",
        ]
        for pattern in patterns:
            match = re.match(pattern, clean_str)
            if match:
                mc_ver = match.group(1)
                forge_ver = match.group(2)
                if mc_ver and forge_ver and (len(mc_ver.split(".")) >= 2) and (len(forge_ver.split(".")) >= 2):
                    return (mc_ver, forge_ver)
        return (None, None)


__all__ = ["ServerDetectionUtils", "ServerDetectionVersionUtils"]
