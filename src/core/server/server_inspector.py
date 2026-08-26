"""伺服器內容完整檢查與證據優先序的唯一 owner"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import orjson

from src.models import EulaState, ServerInspection, ServerInspectionIntent, ServerLaunchTarget
from src.utils import (
    MemoryUtils,
    ServerCommands,
    extract_forge_versions,
    extract_minecraft_version_from_text,
    get_logger,
    read_json,
    read_text_file,
)

logger = get_logger().bind(component="ServerInspector")

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


@dataclass(slots=True)
class _InspectionState:
    loader_type: str = "unknown"
    minecraft_version: str = "unknown"
    loader_version: str = "unknown"


class _InspectionEngine:
    """完整檢查內部使用的證據解析實作"""

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
                            detected = extract_minecraft_version_from_text(str(payload.get(key, "")))
                            if detected:
                                return detected
                if "META-INF/MANIFEST.MF" in names:
                    with jar_file.open("META-INF/MANIFEST.MF") as manifest_file:
                        manifest = manifest_file.read().decode("utf-8", errors="replace")
                    return extract_minecraft_version_from_text(manifest)
        except (OSError, zipfile.BadZipFile, orjson.JSONDecodeError) as e:
            logger.debug(f"讀取 JAR 版本 metadata 失敗 {jar_path}: {e}")
        return None

    @staticmethod
    def _find_loader_args_file(server_path: Path, library_path: str, server_config=None) -> Path | None:
        run_bat = server_path / "run.bat"
        if run_bat.exists():
            with suppress(Exception):
                text = run_bat.read_text(encoding="utf-8", errors="ignore")
                matches = re.findall(r"@([^\s\"']*\.txt)", text, re.IGNORECASE)
                for raw_rel in matches:
                    rel_clean = raw_rel.strip().replace("/", os.sep).replace("\\", os.sep)
                    if "user_jvm_args" in rel_clean.lower():
                        continue
                    candidate = server_path / rel_clean
                    if candidate.exists():
                        return candidate

        loader_lib_dir = server_path / library_path
        if loader_lib_dir.is_dir():
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
            arg_files = [p for p in loader_lib_dir.rglob("win_args.txt") if "user_jvm_args" not in p.name.lower()]
            if arg_files:
                arg_files.sort(key=lambda p: len(p.parts), reverse=True)
                return arg_files[0]

        all_libs = server_path / "libraries"
        if all_libs.is_dir():
            all_args = [
                p
                for p in (list(all_libs.rglob("*win_args.txt")) or list(all_libs.rglob("*args.txt")))
                if "user_jvm_args" not in p.name.lower()
            ]
            if all_args:
                all_args.sort(key=lambda p: len(p.parts), reverse=True)
                return all_args[0]
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
            args_file = _InspectionEngine._find_loader_args_file(server_path, FORGE_LIBRARY_PATH, server_config)
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
            args_file = _InspectionEngine._find_loader_args_file(server_path, NEOFORGE_LIBRARY_PATH, server_config)
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
    def find_startup_script(server_path: Path) -> Path | None:
        """
        尋找伺服器啟動腳本

        Args:
            server_path: 伺服器資料夾路徑

        Returns:
            找到時回傳啟動腳本 Path，否則回傳 None
        """
        for script_name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            candidate_path = server_path / script_name
            if candidate_path.exists():
                return candidate_path
        return None

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
            log_file = _InspectionEngine._get_latest_log_file(server_path)
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
                content = read_text_file(log_file, errors="ignore")
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
            mc, forge_ver = extract_forge_versions(folder)
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
                mc_version = extract_minecraft_version_from_text(jar.stem)
                if mc_version:
                    set_if_unknown("minecraft_version", mc_version)
                    if detection_source and "mc_version" not in detection_source:
                        detection_source["mc_version"] = f"JAR 檔名 {jar.name}"
                loader_match = re.search(
                    r"(?:loader|fabric|quilt|neoforge)[-_.]?(\d+\.\d+(?:\.\d+)?)",
                    jar.stem,
                    re.IGNORECASE,
                )
                if loader_match:
                    set_if_unknown("loader_version", loader_match.group(1))
                    if detection_source and "loader_version" not in detection_source:
                        detection_source["loader_version"] = f"JAR 檔名 {jar.name}"
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
                mc_ver = _InspectionEngine._extract_mc_version_from_jar_file(jar)
                if mc_ver:
                    set_if_unknown("minecraft_version", mc_ver)
                    if detection_source and "mc_version" not in detection_source:
                        detection_source["mc_version"] = f"JAR metadata {jar.name}"
                    return

        def detect_from_version_json():
            fp = server_path / "version.json"
            data = read_json(fp)
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


class ServerInspector:
    """一次讀取伺服器目錄並回傳完整不可變檢查結果"""

    @staticmethod
    def find_main_jar(server_path: Path, loader_type: str, server_config=None) -> str:
        """
        尋找主要 JAR 或 args 啟動參照

        Args:
            server_path: 伺服器資料夾路徑
            loader_type: 模組載入器類型
            server_config: 伺服器設定物件（選填）

        Returns:
            主要 JAR 檔名或 @args.txt 參照字串
        """
        return _InspectionEngine.find_main_jar(server_path, loader_type, server_config)

    @staticmethod
    def find_startup_script(server_path: Path) -> Path | None:
        """
        尋找伺服器啟動腳本

        Args:
            server_path: 伺服器資料夾路徑

        Returns:
            啟動腳本路徑，若不存在則回傳 None
        """
        return _InspectionEngine.find_startup_script(server_path)

    def inspect(self, path: Path | str, intent: ServerInspectionIntent) -> ServerInspection:
        """
        依固定證據順序完整檢查伺服器目錄

        Args:
            path: 待檢查的本機伺服器目錄
            intent: 檢查用途與已登錄期待值

        Returns:
            對應單次磁碟 revision 的完整快照
        """
        server_path = Path(path).resolve(strict=False)
        if not server_path.is_dir():
            return ServerInspection(
                path=server_path,
                revision="",
                is_candidate=False,
                error="伺服器路徑不存在或不是資料夾",
                missing_files=("伺服器資料夾",),
            )

        revision = self._build_revision(server_path)
        jar_paths = tuple(sorted(server_path.glob("*.jar"), key=lambda item: item.name.lower()))
        jar_names = [jar.name for jar in jar_paths]
        is_candidate = _InspectionEngine.is_valid_server_folder(server_path)
        loader = _InspectionEngine.detect_loader_type(server_path, jar_names)
        state = _InspectionState(loader_type=loader)
        evidence: dict[str, str] = {"loader_type": self._loader_evidence(server_path, loader, jar_names)}
        _InspectionEngine.detect_loader_and_version_from_sources(server_path, state, loader, evidence)

        scripts = self._startup_scripts(server_path)
        selected_script = _InspectionEngine.find_startup_script(server_path)
        startup_command = ""
        memory_max_mb = 2048
        memory_min_mb: int | None = None
        for script in scripts:
            command = ServerCommands.extract_startup_script_command(script)
            if command.has_java_command and not startup_command:
                startup_command = command.command_line
            memory_max_mb = command.memory_max_mb or memory_max_mb
            memory_min_mb = command.memory_min_mb if command.memory_min_mb is not None else memory_min_mb
            if startup_command and command.memory_max_mb is not None:
                break
        for args_name in ("user_jvm_args.txt", "jvm.args"):
            args_path = server_path / args_name
            if not args_path.is_file():
                continue
            content = read_text_file(args_path, errors="ignore") or ""
            memory_max_mb = MemoryUtils.parse_memory_setting(content, "Xmx") or memory_max_mb
            memory_min_mb = MemoryUtils.parse_memory_setting(content, "Xms") or memory_min_mb

        main_target = _InspectionEngine.find_main_jar(server_path, state.loader_type, state)
        if selected_script is not None:
            launch_target = ServerLaunchTarget(
                "script",
                selected_script.name,
                startup_command,
                tuple(script.name for script in scripts),
                "依固定啟動腳本優先序選取",
            )
        elif main_target.startswith("@") and (server_path / main_target[1:]).is_file():
            launch_target = ServerLaunchTarget(
                "args",
                main_target,
                candidates=tuple(jar_names),
                reason="依載入器 library args 選取",
            )
        elif main_target and (server_path / main_target).is_file():
            launch_target = ServerLaunchTarget(
                "jar",
                main_target,
                candidates=tuple(jar_names),
                reason="依載入器與主 JAR 優先序選取",
            )
        else:
            launch_target = ServerLaunchTarget("none", candidates=tuple(jar_names), reason="找不到可執行目標")

        eula_state = self._read_eula_state(server_path / "eula.txt")
        missing_files: list[str] = []
        if launch_target.kind == "none":
            missing_files.append("可執行的啟動目標")
        if eula_state == "missing":
            missing_files.append("eula.txt")
        if not (server_path / "server.properties").is_file():
            missing_files.append("server.properties")

        conflicts = self._expected_conflicts(state, intent)
        warnings = list(conflicts)
        if state.minecraft_version.lower() == "unknown":
            warnings.append("無法判斷 Minecraft 版本")
        if eula_state == "unreadable":
            warnings.append("無法讀取 eula.txt")
        if not is_candidate:
            warnings.append("找不到有效的伺服器檔案")
        launchable = is_candidate and launch_target.kind != "none"
        status_ready = launchable and eula_state == "accepted" and not missing_files
        return ServerInspection(
            path=server_path,
            revision=revision,
            is_candidate=is_candidate,
            error="" if is_candidate else "找不到有效的伺服器檔案",
            loader_type=state.loader_type.lower(),
            minecraft_version=state.minecraft_version,
            loader_version=state.loader_version,
            evidence=tuple(sorted((str(key), str(value)) for key, value in evidence.items())),
            conflicts=tuple(conflicts),
            launch_target=launch_target,
            memory_max_mb=memory_max_mb,
            memory_min_mb=memory_min_mb,
            eula_state=eula_state,
            missing_files=tuple(missing_files),
            warnings=tuple(warnings),
            status_ready=status_ready,
            launchable=launchable,
        )

    @staticmethod
    def _build_revision(server_path: Path) -> str:
        digest = hashlib.sha256()
        try:
            entries = sorted(server_path.rglob("*"), key=lambda item: item.relative_to(server_path).as_posix())
            for entry in entries:
                relative = entry.relative_to(server_path).as_posix()
                stat = entry.stat(follow_symlinks=False)
                digest.update(relative.encode("utf-8", errors="surrogatepass"))
                digest.update(b"\0")
                digest.update(str(stat.st_size).encode("ascii"))
                digest.update(b":")
                digest.update(str(stat.st_mtime_ns).encode("ascii"))
                digest.update(b"\n")
        except OSError as exc:
            logger.warning(f"建立伺服器檢查 revision 失敗: {exc}")
            return ""
        return digest.hexdigest()

    @staticmethod
    def _read_eula_state(eula_path: Path) -> EulaState:
        if not eula_path.exists():
            return "missing"
        try:
            content = eula_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "unreadable"
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().lower() == "eula":
                return "accepted" if value.strip().lower() == "true" else "rejected"
        return "rejected"

    @staticmethod
    def _startup_scripts(server_path: Path) -> tuple[Path, ...]:
        ordered: list[Path] = []
        seen: set[Path] = set()
        for name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            candidate = server_path / name
            if candidate.is_file():
                ordered.append(candidate)
                seen.add(candidate.resolve())
        for candidate in sorted(server_path.glob("*.bat"), key=lambda item: item.name.lower()):
            if candidate.resolve() in seen:
                continue
            if ServerCommands.extract_startup_script_command(candidate).has_java_command:
                ordered.append(candidate)
        return tuple(ordered)

    @staticmethod
    def _loader_evidence(server_path: Path, loader: str, jar_names: list[str]) -> str:
        library_paths = {
            "fabric": FABRIC_LIBRARY_PATH,
            "quilt": QUILT_LIBRARY_PATH,
            "forge": FORGE_LIBRARY_PATH,
            "neoforge": NEOFORGE_LIBRARY_PATH,
        }
        library = library_paths.get(loader)
        if library and (server_path / library).exists():
            return f"目錄 {library}"
        match = next((name for name in jar_names if loader in name.lower().replace("-", "")), "")
        return f"JAR {match}" if match else loader

    @staticmethod
    def _expected_conflicts(state: _InspectionState, intent: ServerInspectionIntent) -> list[str]:
        conflicts: list[str] = []
        comparisons = (
            ("loader", intent.expected_loader_type, state.loader_type),
            ("Minecraft", intent.expected_minecraft_version, state.minecraft_version),
            ("loader version", intent.expected_loader_version, state.loader_version),
        )
        for label, expected, actual in comparisons:
            if expected and expected.lower() != "unknown" and actual.lower() != "unknown" and expected != actual:
                conflicts.append(f"已登錄 {label} {expected} 與磁碟證據 {actual} 不一致")
        return conflicts


__all__ = ["ServerInspector"]
