"""伺服器內容完整檢查與證據優先序的唯一 owner"""

from __future__ import annotations

import os
import re
import stat
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import orjson
from packaging.version import Version

from src.models import EulaState, ServerInspection, ServerInspectionIntent, ServerLaunchTarget
from src.utils import (
    ARCHIVE_METADATA_MAX_BYTES,
    SAFE_DIRECTORY_MAX_FILES,
    SAFE_TEXT_FILE_MAX_BYTES,
    VERSION_ZERO,
    HashUtils,
    MemoryUtils,
    ServerCommands,
    extract_forge_versions,
    extract_minecraft_version_from_text,
    get_logger,
    is_path_within,
    is_reparse_point,
    list_bounded_directory,
    open_bounded_zip,
    parse_version_safe,
    read_archive_metadata_bytes,
    read_json,
    read_text_file,
    walk_bounded_tree,
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
_LOADER_LIBRARY_PATHS = {
    "fabric": FABRIC_LIBRARY_PATH,
    "quilt": QUILT_LIBRARY_PATH,
    "forge": FORGE_LIBRARY_PATH,
    "neoforge": NEOFORGE_LIBRARY_PATH,
}

_TXT_ARG_RE = re.compile(r"@([^\s\"']*\.txt)", re.IGNORECASE)
_FORGE_SUBDIR_JAR_RE = re.compile(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?)-.*\.jar")
_FORGE_JAR_RE = re.compile(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?).*\.jar")
_LOADER_STEM_RE = re.compile(r"(?:loader|fabric|quilt|neoforge)[-_.]?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)
_NEOFORGE_DIR_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")


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
            with open_bounded_zip(jar_path) as jar_file:
                payload = read_archive_metadata_bytes(
                    jar_file,
                    "version.json",
                    max_bytes=ARCHIVE_METADATA_MAX_BYTES,
                )
                if payload is not None:
                    payload = orjson.loads(payload)
                    if isinstance(payload, dict):
                        for key in ("id", "name", "release_target"):
                            detected = extract_minecraft_version_from_text(str(payload.get(key, "")))
                            if detected:
                                return detected
                payload = read_archive_metadata_bytes(
                    jar_file,
                    "META-INF/MANIFEST.MF",
                    max_bytes=ARCHIVE_METADATA_MAX_BYTES,
                )
                if payload is not None:
                    manifest = payload.decode("utf-8", errors="replace")
                    return extract_minecraft_version_from_text(manifest)
        except (OSError, ValueError, zipfile.BadZipFile, orjson.JSONDecodeError) as e:
            logger.debug(f"讀取 JAR 版本 metadata 失敗 {jar_path}: {e}")
        return None

    @staticmethod
    def _find_loader_args_file(server_path: Path, library_path: str, server_config=None) -> Path | None:
        run_bat = server_path / "run.bat"
        if run_bat.exists():
            with suppress(Exception):
                text = (
                    read_text_file(
                        run_bat,
                        encoding="utf-8",
                        errors="ignore",
                        max_bytes=SAFE_TEXT_FILE_MAX_BYTES,
                    )
                    or ""
                )
                matches = _TXT_ARG_RE.findall(text)
                for raw_rel in matches:
                    rel_clean = raw_rel.strip().replace("/", os.sep).replace("\\", os.sep)
                    if "user_jvm_args" in rel_clean.lower():
                        continue
                    candidate = (server_path / rel_clean).resolve(strict=False)
                    if is_path_within(server_path, candidate, strict=False) and not is_reparse_point(candidate):
                        return candidate

        def _find_argument_files(root: Path, names: tuple[str, ...]) -> list[Path]:
            matches: list[Path] = []
            try:
                entries = walk_bounded_tree(root, max_entries=SAFE_DIRECTORY_MAX_FILES)
                for current_path, _dirs, files in entries:
                    matches.extend(current_path / file_name for file_name in files if file_name.lower().endswith(names))
            except OSError:
                return []
            return matches

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
            arg_files = [
                path
                for path in _find_argument_files(loader_lib_dir, ("win_args.txt",))
                if "user_jvm_args" not in path.name.lower()
            ]
            if arg_files:
                return max(arg_files, key=lambda p: len(p.parts))

        all_libs = server_path / "libraries"
        if all_libs.is_dir():
            all_args = [
                path
                for path in _find_argument_files(all_libs, ("win_args.txt", "args.txt"))
                if "user_jvm_args" not in path.name.lower()
            ]
            if all_args:
                return max(all_args, key=lambda p: len(p.parts))
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
        try:
            entries = list_bounded_directory(folder_path)
        except OSError:
            return False
        files_by_name = {entry.name.casefold(): entry for entry in entries if entry.is_file()}
        if any(jar_name.casefold() in files_by_name for jar_name in SERVER_JAR_CANDIDATES):
            return True
        for file in entries:
            if file.suffix.lower() != ".jar" or not file.is_file():
                continue
            jar_name = file.name.lower()
            if any(pattern in jar_name for pattern in ["forge", "neoforge", "server", "minecraft"]):
                return True
        server_indicators = ["server.properties", "eula.txt"]
        return any(indicator.casefold() in files_by_name for indicator in server_indicators)

    @staticmethod
    def _get_latest_log_file(server_path: Path) -> Path | None:
        """取得最新的日誌檔，優先級: 時間戳 > 標準名稱"""
        log_candidates = ["latest.log", "server.log", "debug.log"]
        logs_dir = server_path / "logs"
        if not logs_dir.is_dir():
            return None
        try:
            log_entries = list_bounded_directory(logs_dir)
        except OSError:
            return None
        files_by_name = {entry.name.casefold(): entry for entry in log_entries if entry.is_file()}
        found_logs = [files_by_name[name] for name in log_candidates if name in files_by_name]
        if not found_logs:
            found_logs = [entry for entry in log_entries if entry.suffix.lower() == ".log" and entry.is_file()]
        if not found_logs:
            return None
        latest_log = max(found_logs, key=lambda p: p.stat().st_mtime)
        logger.debug(f"選擇日誌檔: {latest_log.name}")
        return latest_log

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
        try:
            root_entries = list_bounded_directory(server_path)
        except OSError:
            root_entries = []
        jar_files = [entry for entry in root_entries if entry.suffix.lower() == ".jar" and entry.is_file()]

        def is_unknown(value: str | None) -> bool:
            return value in (None, "", "unknown", "Unknown", "無")

        def set_if_unknown(attr_name: str, value: str):
            if is_unknown(getattr(config, attr_name)):
                setattr(config, attr_name, value)

        def version_directory_key(path: Path) -> tuple[Version, str]:
            return (parse_version_safe(path.name, fallback=VERSION_ZERO), path.name.casefold())

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
                content = read_text_file(
                    log_file,
                    errors="ignore",
                    max_bytes=SAFE_TEXT_FILE_MAX_BYTES,
                    allowed_root=server_path,
                )
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
            try:
                subdirs = [d for d in list_bounded_directory(forge_dir) if d.is_dir()]
            except OSError:
                return
            if not subdirs:
                return
            selected_subdir = min(
                subdirs,
                key=version_directory_key,
            )
            folder = selected_subdir.name
            mc, forge_ver = extract_forge_versions(folder)
            if mc and forge_ver:
                set_if_unknown("minecraft_version", mc)
                set_if_unknown("loader_version", forge_ver)
            else:
                try:
                    jars = [jar for jar in list_bounded_directory(selected_subdir) if jar.suffix.lower() == ".jar"]
                except OSError:
                    return
                for jar in jars:
                    m2 = _FORGE_SUBDIR_JAR_RE.match(jar.name)
                    if m2:
                        mc2, forge_ver2 = m2.groups()
                        set_if_unknown("minecraft_version", mc2)
                        set_if_unknown("loader_version", forge_ver2)
                        break

        def detect_from_jars():
            for jar in jar_files:
                name_lower = jar.name.lower()
                if is_unknown(config.loader_type):
                    if "fabric" in name_lower:
                        config.loader_type = "fabric"
                    elif "forge" in name_lower:
                        config.loader_type = "forge"
                    elif name_lower in {"server.jar", "minecraft_server.jar"}:
                        config.loader_type = "vanilla"
                m = _FORGE_JAR_RE.search(jar.name)
                if m:
                    mc, forge_ver = m.groups()
                    set_if_unknown("minecraft_version", mc)
                    set_if_unknown("loader_version", forge_ver)
                mc_version = extract_minecraft_version_from_text(jar.stem)
                if mc_version:
                    set_if_unknown("minecraft_version", mc_version)
                    if detection_source and "mc_version" not in detection_source:
                        detection_source["mc_version"] = f"JAR 檔名 {jar.name}"
                loader_match = _LOADER_STEM_RE.search(jar.stem)
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
            preferred_map = {"server.jar": 0, "minecraft_server.jar": 1}
            preferred_jars: list[tuple[int, Path]] = []
            other_jars: list[Path] = []
            for jar in jar_files:
                name_lower = jar.name.casefold()
                rank = preferred_map.get(name_lower)
                if rank is not None:
                    preferred_jars.append((rank, jar))
                elif "installer" not in name_lower:
                    other_jars.append(jar)
            preferred_jars.sort(key=lambda item: item[0])
            for jar in [j for _, j in preferred_jars] + other_jars:
                mc_ver = _InspectionEngine._extract_mc_version_from_jar_file(jar)
                if mc_ver:
                    set_if_unknown("minecraft_version", mc_ver)
                    if detection_source and "mc_version" not in detection_source:
                        detection_source["mc_version"] = f"JAR metadata {jar.name}"
                    return

        def detect_from_version_json():
            fp = server_path / "version.json"
            data = read_json(fp, max_bytes=ARCHIVE_METADATA_MAX_BYTES, allowed_root=server_path)
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
            try:
                subdirs = [d for d in list_bounded_directory(fabric_dir) if d.is_dir()]
            except OSError:
                return
            if not subdirs:
                return
            selected_subdir = max(
                subdirs,
                key=version_directory_key,
            )
            set_if_unknown("loader_version", selected_subdir.name)
            if detection_source:
                detection_source["loader_version"] = "Fabric 函式庫目錄"

        def detect_from_quilt_lib():
            quilt_dir = server_path / "libraries" / "org" / "quiltmc" / "quilt-loader"
            if not quilt_dir.is_dir():
                return
            try:
                subdirs = [d for d in list_bounded_directory(quilt_dir) if d.is_dir()]
            except OSError:
                return
            if not subdirs:
                return
            selected_subdir = max(
                subdirs,
                key=version_directory_key,
            )
            set_if_unknown("loader_version", selected_subdir.name)
            if detection_source:
                detection_source["loader_version"] = "Quilt 函式庫目錄"

        def detect_from_neoforge_lib():
            neoforge_dir = server_path / "libraries" / "net" / "neoforged" / "neoforge"
            if not neoforge_dir.is_dir():
                return
            try:
                subdirs = [d for d in list_bounded_directory(neoforge_dir) if d.is_dir()]
            except OSError:
                return
            if not subdirs:
                return
            folder = max(
                subdirs,
                key=version_directory_key,
            ).name
            set_if_unknown("loader_version", folder)
            if detection_source:
                detection_source["loader_version"] = "NeoForge 函式庫目錄"
            m = _NEOFORGE_DIR_VERSION_RE.match(folder)
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
        尋找主要 JAR 檔案，根據載入器類型和伺服器設定進行優先順序檢測

        Args:
            server_path: 伺服器資料夾路徑
            loader_type: 載入器類型
            server_config: 伺服器設定物件

        Returns:
            主要 JAR 檔或啟動參照字串
        """
        loader_type = (loader_type or "").lower()

        def _args_target(args_file: Path | None) -> str:
            if args_file is None or not args_file.exists():
                return ""
            try:
                relative_path = args_file.relative_to(server_path)
            except ValueError:
                relative_path = Path(args_file.name)
            target = f"@{relative_path.as_posix()}"
            return target if ServerCommands.is_safe_batch_argument(target) else ""

        try:
            root_entries = list_bounded_directory(server_path)
        except OSError:
            root_entries = []
        jar_files = [entry for entry in root_entries if entry.suffix.lower() == ".jar" and entry.is_file()]

        if loader_type == "forge":
            args_file = _InspectionEngine._find_loader_args_file(server_path, FORGE_LIBRARY_PATH, server_config)
            args_target = _args_target(args_file)
            if args_target:
                return args_target
            for jar_file in jar_files:
                if (
                    not is_reparse_point(jar_file)
                    and ServerCommands.is_safe_batch_argument(jar_file.name)
                    and "forge" in jar_file.name.lower()
                    and "neo" not in jar_file.name.lower()
                ):
                    return jar_file.name
        elif loader_type == "neoforge":
            args_file = _InspectionEngine._find_loader_args_file(server_path, NEOFORGE_LIBRARY_PATH, server_config)
            args_target = _args_target(args_file)
            if args_target:
                return args_target
            for jar_file in jar_files:
                if (
                    not is_reparse_point(jar_file)
                    and ServerCommands.is_safe_batch_argument(jar_file.name)
                    and "neoforge" in jar_file.name.lower().replace("-", "").replace("_", "")
                ):
                    return jar_file.name
        elif loader_type == "fabric":
            for fabric_jar in FABRIC_JAR_NAMES:
                if (server_path / fabric_jar).is_file() and not is_reparse_point(server_path / fabric_jar):
                    return fabric_jar
        elif loader_type == "quilt":
            for quilt_jar in QUILT_JAR_NAMES:
                if (server_path / quilt_jar).is_file() and not is_reparse_point(server_path / quilt_jar):
                    return quilt_jar
        for jar_name in ["server.jar", "minecraft_server.jar"]:
            if (server_path / jar_name).is_file() and not is_reparse_point(server_path / jar_name):
                return jar_name
        safe_jars = [jar_file for jar_file in jar_files if ServerCommands.is_safe_batch_argument(jar_file.name)]
        return safe_jars[0].name if safe_jars else "server.jar"

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
            if candidate_path.is_file() and not is_reparse_point(candidate_path):
                command = ServerCommands.extract_startup_script_command(candidate_path)
                if command.has_java_command and not command.unsafe:
                    return candidate_path
        return None

    def inspect(self, path: Path | str, intent: ServerInspectionIntent) -> ServerInspection:
        """
        依固定證據順序完整檢查伺服器目錄

        Args:
            path: 待檢查的本機伺服器目錄
            intent: 檢查用途與已登錄期待值

        Returns:
            對應單次磁碟 revision 的完整快照
        """
        raw_server_path = Path(path)
        if is_reparse_point(raw_server_path):
            return ServerInspection(
                path=raw_server_path,
                revision="",
                is_candidate=False,
                error="伺服器路徑不可為符號連結或 reparse point",
            )
        server_path = raw_server_path.resolve(strict=False)
        if not server_path.is_dir():
            return ServerInspection(
                path=server_path,
                revision="",
                is_candidate=False,
                error="伺服器路徑不存在或不是資料夾",
                missing_files=("伺服器資料夾",),
            )

        if intent and intent.purpose == "status":
            revision = self._build_status_revision(server_path)
        elif intent and intent.purpose in {"launch", "redetect"}:
            revision = ""
        else:
            revision = self._build_revision(server_path)
        try:
            jar_paths = tuple(
                sorted(
                    (
                        entry
                        for entry in list_bounded_directory(server_path)
                        if entry.suffix.lower() == ".jar" and entry.is_file()
                    ),
                    key=lambda item: item.name.lower(),
                )
            )
        except OSError:
            jar_paths = ()
        jar_names = [jar.name for jar in jar_paths]
        is_candidate = _InspectionEngine.is_valid_server_folder(server_path)
        loader = _InspectionEngine.detect_loader_type(server_path, jar_names)
        state = _InspectionState(loader_type=loader)
        evidence: dict[str, str] = {"loader_type": self._loader_evidence(server_path, loader, jar_names)}
        _InspectionEngine.detect_loader_and_version_from_sources(server_path, state, loader, evidence)

        scripts = self._startup_scripts(server_path)
        selected_script = ServerInspector.find_startup_script(server_path)
        startup_command = ""
        memory_max_mb = 2048
        memory_min_mb: int | None = None
        metadata_scripts = list(scripts)
        for script_name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            candidate = server_path / script_name
            if candidate.is_file() and not is_reparse_point(candidate) and candidate not in metadata_scripts:
                metadata_scripts.append(candidate)
        for script in metadata_scripts:
            command = ServerCommands.extract_startup_script_command(script)
            memory_max_mb = command.memory_max_mb or memory_max_mb
            memory_min_mb = command.memory_min_mb if command.memory_min_mb is not None else memory_min_mb
            if command.unsafe:
                continue
            if command.has_java_command and not startup_command:
                startup_command = command.command_line
            if startup_command and command.memory_max_mb is not None:
                break
        for args_name in ("user_jvm_args.txt", "jvm.args"):
            args_path = server_path / args_name
            if not args_path.is_file():
                continue
            content = (
                read_text_file(
                    args_path,
                    errors="ignore",
                    max_bytes=SAFE_TEXT_FILE_MAX_BYTES,
                    allowed_root=server_path,
                )
                or ""
            )
            memory_max_mb = MemoryUtils.parse_memory_setting(content, "Xmx") or memory_max_mb
            memory_min_mb = MemoryUtils.parse_memory_setting(content, "Xms") or memory_min_mb

        main_target = ServerInspector.find_main_jar(server_path, state.loader_type, state)
        if selected_script is not None:
            launch_target = ServerLaunchTarget(
                "script",
                selected_script.name,
                startup_command,
                tuple(script.name for script in scripts),
                "依固定啟動腳本優先序選取",
            )
        elif (
            main_target.startswith("@")
            and (server_path / main_target[1:]).is_file()
            and not is_reparse_point(server_path / main_target[1:])
        ):
            launch_target = ServerLaunchTarget(
                "args",
                main_target,
                candidates=tuple(jar_names),
                reason="依載入器 library args 選取",
            )
        elif main_target and (server_path / main_target).is_file() and not is_reparse_point(server_path / main_target):
            launch_target = ServerLaunchTarget(
                "jar",
                main_target,
                candidates=tuple(jar_names),
                reason="依載入器與主 JAR 優先序選取",
            )
        else:
            launch_target = ServerLaunchTarget("none", candidates=tuple(jar_names), reason="找不到可執行目標")

        if intent and intent.purpose in {"launch", "redetect"}:
            revision = self._build_launch_revision(server_path, launch_target)

        eula_state = self._read_eula_state(server_path / "eula.txt", allowed_root=server_path)
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
    def _build_status_revision(server_path: Path) -> str:
        digest = HashUtils.new_hasher("sha256")
        if digest is None:
            return ""
        try:
            for item in sorted(list_bounded_directory(server_path), key=lambda p: p.name.lower()):
                if item.name.startswith(".msm-"):
                    continue
                stat = item.stat(follow_symlinks=False)
                digest.update(
                    f"{item.name}\0{stat.st_size}:{stat.st_mtime_ns}\n".encode("utf-8", errors="surrogatepass")
                )
        except OSError as e:
            logger.warning(f"建立伺服器狀態 revision 失敗: {e}")
            return ""
        return digest.hexdigest()

    @staticmethod
    def _build_revision(server_path: Path) -> str:
        digest = HashUtils.new_hasher("sha256")
        if digest is None:
            return ""
        try:
            for root_path, dirs, files in walk_bounded_tree(
                server_path,
                max_entries=SAFE_DIRECTORY_MAX_FILES,
            ):
                for entry_name in (*dirs, *files):
                    entry = root_path / entry_name
                    relative = entry.relative_to(server_path).as_posix()
                    metadata = entry.stat(follow_symlinks=False)
                    digest.update(
                        f"{relative}\0{metadata.st_size}:{metadata.st_mtime_ns}\n".encode(
                            "utf-8", errors="surrogatepass"
                        )
                    )
        except OSError as e:
            logger.warning(f"建立伺服器檢查 revision 失敗: {e}")
            return ""
        return digest.hexdigest()

    @staticmethod
    def _build_launch_revision(server_path: Path, launch_target: ServerLaunchTarget) -> str:
        """只追蹤會改變啟動行為的檔案 metadata"""
        relative_names = {
            "eula.txt",
            "server.properties",
            "jvm.args",
            "user_jvm_args.txt",
            *ServerCommands.STARTUP_SCRIPT_CANDIDATES,
        }
        if launch_target.value:
            relative_names.add(launch_target.value.removeprefix("@"))
        digest = HashUtils.new_hasher("sha256")
        if digest is None:
            return ""
        for relative_name in sorted(relative_names, key=str.casefold):
            candidate = server_path / relative_name
            try:
                metadata = candidate.stat(follow_symlinks=False)
                if is_reparse_point(candidate) or not stat.S_ISREG(metadata.st_mode):
                    continue
                digest.update(
                    f"{relative_name.casefold()}\0{metadata.st_size}:{metadata.st_mtime_ns}\n".encode(
                        "utf-8", errors="surrogatepass"
                    )
                )
            except FileNotFoundError:
                continue
            except OSError as e:
                logger.warning(f"建立啟動證據 revision 失敗 {candidate.name}: {e}")
                return ""
        return digest.hexdigest()

    @staticmethod
    def parse_eula_text(content: str) -> EulaState:
        """
        解析 EULA 文字內容的同意狀態

        Args:
            content: eula.txt 的文字內容

        Returns:
            accepted 或 rejected
        """
        for raw_line in content.splitlines():
            line = raw_line.strip()
            key, sep, value = line.partition("=")
            if not sep or not key or key.startswith("#"):
                continue
            if key.strip().lower() == "eula":
                return "accepted" if value.strip().lower() == "true" else "rejected"
        return "rejected"

    @classmethod
    def _read_eula_state(cls, eula_path: Path, *, allowed_root: Path | None = None) -> EulaState:
        if not eula_path.exists():
            return "missing"
        content = read_text_file(
            eula_path,
            encoding="utf-8",
            errors="replace",
            max_bytes=SAFE_TEXT_FILE_MAX_BYTES,
            allowed_root=allowed_root,
        )
        if content is None:
            return "unreadable"
        return cls.parse_eula_text(content)

    @staticmethod
    def _startup_scripts(server_path: Path) -> tuple[Path, ...]:
        ordered: list[Path] = []
        seen: set[Path] = set()
        for name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            candidate = server_path / name
            if candidate.is_file() and not is_reparse_point(candidate):
                command = ServerCommands.extract_startup_script_command(candidate)
                if command.has_java_command and not command.unsafe:
                    resolved_candidate = candidate.resolve()
                    ordered.append(candidate)
                    seen.add(resolved_candidate)
        try:
            candidates = sorted(
                (
                    entry
                    for entry in list_bounded_directory(server_path)
                    if entry.suffix.lower() == ".bat" and entry.is_file()
                ),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            candidates = []
        for candidate in candidates:
            resolved_candidate = candidate.resolve()
            if resolved_candidate in seen:
                continue
            command = ServerCommands.extract_startup_script_command(candidate)
            if command.has_java_command and not command.unsafe:
                ordered.append(candidate)
                seen.add(resolved_candidate)
        return tuple(ordered)

    @staticmethod
    def _loader_evidence(server_path: Path, loader: str, jar_names: list[str]) -> str:
        library = _LOADER_LIBRARY_PATHS.get(loader)
        if library and (server_path / library).exists():
            return f"目錄 {library}"
        match = next((name for name in jar_names if loader in name.lower().replace("-", "")), "")
        return f"JAR {match}" if match else loader

    @staticmethod
    def _expected_conflicts(state: _InspectionState, intent: ServerInspectionIntent) -> list[str]:
        comparisons = (
            ("loader", intent.expected_loader_type, state.loader_type),
            ("Minecraft", intent.expected_minecraft_version, state.minecraft_version),
            ("loader version", intent.expected_loader_version, state.loader_version),
        )
        return [
            f"已登錄 {label} {expected} 與磁碟證據 {actual} 不一致"
            for label, expected, actual in comparisons
            if expected and expected.lower() != "unknown" and actual.lower() != "unknown" and expected != actual
        ]


__all__ = ["ServerInspector"]
