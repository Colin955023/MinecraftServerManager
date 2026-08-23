"""交易式伺服器匯入、批次探索與重新偵測"""

from __future__ import annotations

import shutil
import time
import uuid
import zipfile
from collections.abc import Callable, Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from src.core import ServerCRUD
from src.models import (
    ConflictType,
    ImportMode,
    ImportSourceKind,
    ServerConfig,
    ServerDetectionScratch,
    ServerImportBatchResult,
    ServerImportInspection,
    ServerImportResult,
)
from src.utils import (
    ImportCancelledError,
    MemoryUtils,
    PathUtils,
    ServerCommands,
    ServerDetectionUtils,
    atomic_write_bytes,
    atomic_write_json,
    get_logger,
)

logger = get_logger().bind(component="ServerImport")

ProgressCallback = Callable[[int, str], None]
CancelCheck = Callable[[], bool]
_DetectionScratch = ServerDetectionScratch
_ImportCancelled = ImportCancelledError


class ServerImportService:
    """從唯讀檢查到檔案與設定提交的唯一 owner"""

    _MARKER_NAME = ".msm-server-import.json"
    _BACKUP_NAME = ".msm-start-server.backup"
    _STAGING_GLOB = ".msm-import-*.staging"

    def __init__(self, server_crud: ServerCRUD) -> None:
        self.server_crud = server_crud
        self._root = server_crud.servers_root.resolve()
        self._lock = server_crud.operation_lock
        self.recover_orphans()

    def inspect(
        self,
        source_path: Path | str,
        name: str | None = None,
        *,
        mode: ImportMode = "import",
    ) -> ServerImportInspection:
        """
        唯讀檢查來源；ZIP 的內容偵測延後至安全 staging

        Args:
            source_path: 外部資料夾、ZIP，或 root 直接子目錄
            name: 受管伺服器名稱；省略時取來源檔名
            mode: 新匯入或已註冊項目的重新偵測

        Returns:
            不可變且可在提交前呈現的候選快照
        """
        source = Path(source_path).resolve(strict=True)
        normalized_name, final_path = self._validate_name(name or source.stem)
        if mode not in {"import", "redetect"}:
            raise ValueError("不支援的匯入模式")
        if source.is_file():
            if source.suffix.lower() != ".zip":
                raise ValueError("目前只支援 ZIP 壓縮檔")
            kind: ImportSourceKind = "archive"
        elif source.is_dir():
            kind = "in_place" if source.parent == self._root and source == final_path else "directory"
        else:
            raise ValueError("匯入來源不是檔案或資料夾")

        previous = self.server_crud.servers.get(normalized_name)
        disk_exists = final_path.exists() and kind != "in_place"
        config_exists = previous is not None

        if mode == "redetect":
            if previous is None or Path(previous.path).resolve(strict=False) != final_path or kind != "in_place":
                raise ValueError("重新偵測只允許目前 root 內已註冊的直接子目錄")
            conflict_type: ConflictType = "none"
            conflict = False
        else:
            if kind == "in_place":
                if config_exists:
                    conflict_type = "config"
                    conflict = True
                else:
                    conflict_type = "none"
                    conflict = False
            else:
                if disk_exists and config_exists:
                    conflict_type = "both"
                    conflict = True
                elif disk_exists:
                    conflict_type = "disk"
                    conflict = True
                elif config_exists:
                    conflict_type = "config"
                    conflict = True
                else:
                    conflict_type = "none"
                    conflict = False

        if kind == "directory":
            if source == self._root or PathUtils.is_path_within(source, final_path, strict=False):
                raise ValueError("來源不可等於伺服器根目錄或包含匯入目標")
            symlink = self._first_symlink(source)
            if symlink is not None:
                raise ValueError(f"資料夾來源不可包含符號連結：{symlink.name}")

        warnings: list[str] = []
        if conflict_type == "both":
            warnings.append("同名伺服器已存在於磁碟與設定中")
        elif conflict_type == "disk":
            warnings.append("目標伺服器資料夾已存在於磁碟上")
        elif conflict_type == "config":
            warnings.append("同名伺服器已註冊於設定中")

        if kind == "archive":
            return self._inspect_zip(
                source,
                normalized_name,
                final_path,
                mode,
                transaction_id=uuid.uuid4().hex,
                conflict_type=conflict_type,
                extra_warnings=warnings,
                committable=not conflict,
            )
        return self._inspect_directory(
            source,
            normalized_name,
            final_path,
            kind,
            mode,
            transaction_id=uuid.uuid4().hex,
            conflict_type=conflict_type,
            extra_warnings=warnings,
            committable=not conflict,
        )

    def inspect_registered(self, name: str) -> ServerImportInspection:
        """
        唯讀檢查已註冊且位於固定 root 直接子目錄的實例

        Args:
            name: 已註冊伺服器名稱

        Returns:
            重新偵測模式的不可變候選快照
        """
        config = self.server_crud.servers.get(name)
        if config is None:
            raise KeyError(f"找不到伺服器設定：{name}")
        return self.inspect(config.path, name, mode="redetect")

    def discover(self) -> tuple[ServerImportInspection, ...]:
        """
        探索固定 root 的直接子目錄，不切換 repository context

        Returns:
            依名稱排序的有效伺服器候選快照
        """
        inspections: list[ServerImportInspection] = []
        for child in sorted(self._root.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir() or child.name.startswith(".msm-"):
                continue
            if not ServerDetectionUtils.is_valid_server_folder(child):
                continue
            mode: ImportMode = "redetect" if child.name in self.server_crud.servers else "import"
            inspections.append(self.inspect(child, child.name, mode=mode))
        return tuple(inspections)

    def execute(
        self,
        inspection: ServerImportInspection,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ServerImportResult:
        """
        執行單一候選的準備、提交與失敗補償

        Args:
            inspection: 由本服務產生的不可變候選
            progress_callback: 接收百分比與狀態文字的選用回呼
            cancel_check: 回傳 True 時要求安全取消的選用回呼

        Returns:
            明確區分完成、略過、取消與失敗的結果
        """
        cancel = cancel_check or (lambda: False)
        if not inspection.committable:
            return ServerImportResult("skipped", "候選有名稱或路徑衝突", inspection.name, warnings=inspection.warnings)
        with self._lock:
            return self._execute_locked(inspection, progress_callback, cancel)

    def execute_batch(
        self,
        inspections: Iterable[ServerImportInspection],
        *,
        cancel_check: CancelCheck | None = None,
    ) -> ServerImportBatchResult:
        """
        逐項執行相同交易並保留每一項結果

        Args:
            inspections: 已完成唯讀檢查的候選集合
            cancel_check: 批次項目間與單項安全點共用的取消檢查

        Returns:
            不會將部分失敗誤報為成功的批次結果
        """
        results: list[ServerImportResult] = []
        for inspection in inspections:
            if cancel_check is not None and cancel_check():
                results.append(ServerImportResult("cancelled", "批次作業已取消", inspection.name))
                break
            results.append(self.execute(inspection, cancel_check=cancel_check))
        return ServerImportBatchResult(tuple(results))

    def _execute_locked(
        self,
        inspection: ServerImportInspection,
        progress_callback: ProgressCallback | None,
        cancel_check: CancelCheck,
    ) -> ServerImportResult:
        staging = self._root / f".msm-import-{inspection.transaction_id}.staging"
        work_path = inspection.source_path
        moved_to_final = False
        registered = False
        script_changed = False
        previous = self.server_crud.servers.get(inspection.name)
        previous_script: bytes | None = None
        previous_script_existed = False
        phase = "validate"
        active = inspection
        try:
            self._revalidate(inspection, previous)
            self._check_cancel(cancel_check)
            if inspection.source_kind != "in_place":
                phase = "materialize"
                self._check_disk_space(inspection.source_path)
                staging.mkdir(exist_ok=False)
                self._write_marker(staging, inspection, "materializing")
                if inspection.source_kind == "archive":
                    PathUtils.safe_extract_zip(
                        inspection.source_path,
                        staging,
                        progress_callback=lambda done, total: self._emit_units(
                            progress_callback, done, total, 5, 65, "正在解壓縮伺服器..."
                        ),
                    )
                    self._flatten_single_wrapper(staging)
                elif not PathUtils.copy_dir(
                    inspection.source_path,
                    staging,
                    progress_callback=lambda done, total: self._emit_units(
                        progress_callback, done, total, 5, 65, "正在複製伺服器..."
                    ),
                ):
                    raise RuntimeError("複製伺服器資料夾失敗")
                work_path = staging
                active = self._inspect_directory(
                    work_path,
                    inspection.name,
                    inspection.final_path,
                    inspection.source_kind,
                    inspection.mode,
                    transaction_id=inspection.transaction_id,
                )
                if not active.committable:
                    raise RuntimeError("staging 內容不是有效的 Minecraft 伺服器")

            phase = "prepare_script"
            self._check_cancel(cancel_check)
            self._emit(progress_callback, 72, "正在準備受管啟動腳本...")
            config = active.build_config(work_path, previous)
            managed_script = work_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
            if inspection.source_kind == "in_place":
                previous_script_existed = managed_script.is_file()
                previous_script = managed_script.read_bytes() if previous_script_existed else None
                if previous_script_existed and not atomic_write_bytes(
                    work_path / self._BACKUP_NAME, previous_script or b""
                ):
                    raise RuntimeError("無法保存既有啟動腳本快照")
                self._write_marker(work_path, inspection, "script_preparing")
            override = (
                ServerCommands.ensure_nogui_in_command(
                    ServerCommands.replace_startup_command_java_path(active.startup_command, config)
                )
                if active.startup_command
                else None
            )
            if not self.server_crud.create_launch_script(config, java_command_override=override):
                raise RuntimeError("建立受管啟動腳本失敗")
            script_changed = True
            self._write_marker(work_path, inspection, "prepared")

            phase = "commit"
            self._check_cancel(cancel_check)
            self._emit(progress_callback, 88, "正在提交伺服器實例...")
            if inspection.source_kind != "in_place":
                if inspection.final_path.exists():
                    raise FileExistsError("匯入目標在提交前已存在")
                staging.rename(inspection.final_path)
                moved_to_final = True
                work_path = inspection.final_path
                config.path = str(work_path)
                self._write_marker(work_path, inspection, "moved")
            self.server_crud.servers[inspection.name] = config
            registered = True
            if not self.server_crud.write_servers_config():
                raise RuntimeError("儲存 servers_config.json 失敗")
            self._write_marker(work_path, inspection, "committed")
            self._remove_transaction_files(work_path)
            ServerCommands.cleanup_redundant_startup_scripts(work_path)
            self._emit(progress_callback, 100, "伺服器匯入完成")
            return ServerImportResult(
                "completed",
                f"伺服器 {inspection.name} 已匯入",
                inspection.name,
                config=config,
                warnings=active.warnings,
                evidence=active.evidence,
            )
        except _ImportCancelled:
            cleanup = self._compensate(
                inspection,
                staging,
                moved_to_final,
                registered,
                previous,
                script_changed,
                previous_script_existed,
                previous_script,
            )
            return ServerImportResult("cancelled", "使用者已取消匯入", inspection.name, cleanup_complete=cleanup)
        except FileExistsError as exc:
            cleanup = self._compensate(
                inspection,
                staging,
                moved_to_final,
                registered,
                previous,
                script_changed,
                previous_script_existed,
                previous_script,
            )
            return ServerImportResult("skipped", str(exc), inspection.name, cleanup_complete=cleanup)
        except Exception as exc:
            cleanup = self._compensate(
                inspection,
                staging,
                moved_to_final,
                registered,
                previous,
                script_changed,
                previous_script_existed,
                previous_script,
            )
            diagnostic_id = self._record_diagnostic(inspection, phase, exc)
            logger.exception(f"伺服器匯入交易失敗 [{diagnostic_id}]: {exc}")
            return ServerImportResult(
                "failed",
                f"匯入失敗；診斷編號：{diagnostic_id}",
                inspection.name,
                diagnostic_id=diagnostic_id,
                cleanup_complete=cleanup,
            )

    def recover_orphans(self) -> None:
        """清理 crash staging，並完成或回復帶 marker 的實例"""
        with self._lock:
            for staging in self._root.glob(self._STAGING_GLOB):
                if staging.is_dir():
                    PathUtils.delete_within(self._root, staging)
            for candidate in self._root.iterdir():
                marker = candidate / self._MARKER_NAME
                if not candidate.is_dir() or not marker.is_file():
                    continue
                state = ""
                payload: dict[str, Any] = {}
                try:
                    loaded = PathUtils.load_json(marker, {}) or {}
                    if isinstance(loaded, dict):
                        payload = loaded
                    state = str(payload.get("state", ""))
                except Exception as exc:
                    logger.warning(f"無法解析匯入交易 marker {marker}: {exc}")
                config = self.server_crud.servers.get(candidate.name)
                registered = config is not None and Path(config.path).resolve(strict=False) == candidate.resolve()
                if state == "committed" and registered:
                    self._remove_transaction_files(candidate)
                elif (candidate / self._BACKUP_NAME).is_file():
                    target = payload.get("target_config", {}) if isinstance(payload, dict) else {}
                    if not registered or not self._config_matches_marker(config, target):
                        self._restore_script(candidate, True, (candidate / self._BACKUP_NAME).read_bytes())
                    self._remove_transaction_files(candidate)
                elif not registered:
                    PathUtils.delete_within(self._root, candidate)
                else:
                    self._remove_transaction_files(candidate)

    def _validate_name(self, name: str) -> tuple[str, Path]:
        normalized = str(name or "")
        if not normalized or normalized != normalized.strip():
            raise ValueError("伺服器名稱不可為空白或包含前後空白")
        if Path(normalized).name != normalized or normalized in {".", ".."}:
            raise ValueError("伺服器名稱不可包含路徑片段")
        if any(char in normalized for char in '<>:"/\\|?*') or normalized.endswith((".", " ")):
            raise ValueError("伺服器名稱包含 Windows 不允許的字元")
        final_path = (self._root / normalized).resolve(strict=False)
        if final_path.parent != self._root or not PathUtils.is_path_within(self._root, final_path, strict=False):
            raise ValueError("無效的伺服器名稱（路徑遍歷偵測）")
        return normalized, final_path

    def _inspect_directory(
        self,
        path: Path,
        name: str,
        final_path: Path,
        kind: ImportSourceKind,
        mode: ImportMode,
        *,
        transaction_id: str,
        conflict_type: ConflictType = "none",
        extra_warnings: list[str] | None = None,
        committable: bool = True,
    ) -> ServerImportInspection:
        if not ServerDetectionUtils.is_valid_server_folder(path):
            return self._empty_inspection(
                path,
                name,
                final_path,
                kind,
                mode,
                [*(extra_warnings or []), "找不到有效的伺服器檔案"],
                False,
                transaction_id=transaction_id,
                conflict_type=conflict_type,
            )
        jars = [jar.name for jar in path.glob("*.jar")]
        loader = ServerDetectionUtils.detect_loader_type(path, jars)
        scratch = _DetectionScratch(loader_type=loader)
        evidence: dict[str, str] = {"loader_type": self._loader_evidence(path, loader, jars)}
        ServerDetectionUtils.detect_loader_and_version_from_sources(path, scratch, loader, evidence)
        scripts = self._startup_scripts(path)
        command = ""
        memory_max = 2048
        memory_min: int | None = None
        for script in scripts:
            detected = ServerCommands.extract_startup_script_command(script)
            if detected.has_java_command and not command:
                command = detected.command_line
            memory_max = detected.memory_max_mb or memory_max
            memory_min = detected.memory_min_mb if detected.memory_min_mb is not None else memory_min
            if command and detected.memory_max_mb is not None:
                break
        for args_name in ("user_jvm_args.txt", "jvm.args"):
            content = (
                PathUtils.read_text_file(path / args_name, errors="ignore") if (path / args_name).is_file() else ""
            )
            if content:
                memory_max = MemoryUtils.parse_memory_setting(content, "Xmx") or memory_max
                memory_min = MemoryUtils.parse_memory_setting(content, "Xms") or memory_min
        missing = tuple(ServerDetectionUtils.get_missing_server_files(path))
        warnings = list(extra_warnings or [])
        if scratch.minecraft_version.lower() == "unknown":
            warnings.append("無法判斷 Minecraft 版本")
        return ServerImportInspection(
            transaction_id=transaction_id,
            mode=mode,
            source_kind=kind,
            source_path=path,
            name=name,
            final_path=final_path,
            loader_type=scratch.loader_type.lower(),
            minecraft_version=scratch.minecraft_version,
            loader_version=scratch.loader_version,
            memory_max_mb=memory_max,
            memory_min_mb=memory_min,
            eula_accepted=ServerDetectionUtils.detect_eula_acceptance(path),
            main_jar=ServerDetectionUtils.find_main_jar(path, scratch.loader_type, scratch),
            startup_scripts=tuple(script.name for script in scripts),
            startup_command=command,
            evidence=tuple(sorted((str(key), str(value)) for key, value in evidence.items())),
            missing_files=missing,
            warnings=tuple(warnings),
            committable=committable,
            conflict_type=conflict_type,
        )

    def _inspect_zip(
        self,
        archive_path: Path,
        name: str,
        final_path: Path,
        mode: ImportMode,
        *,
        transaction_id: str,
        conflict_type: ConflictType = "none",
        extra_warnings: list[str] | None = None,
        committable: bool = True,
    ) -> ServerImportInspection:
        import re

        warnings = list(extra_warnings or [])
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                namelist = zf.namelist()
                top_levels = {p.split("/")[0] for p in namelist if "/" in p}
                single_wrapper = ""
                if len(top_levels) == 1:
                    wrapper_cand = next(iter(top_levels))
                    if all(p.startswith(f"{wrapper_cand}/") or p == wrapper_cand for p in namelist):
                        single_wrapper = f"{wrapper_cand}/"

                def clean_name(p: str) -> str:
                    return p[len(single_wrapper) :] if single_wrapper and p.startswith(single_wrapper) else p

                cleaned_files = [clean_name(p) for p in namelist if not p.endswith("/")]
                root_files = [f for f in cleaned_files if "/" not in f]
                jars = [f for f in root_files if f.lower().endswith(".jar")]

                loader = "vanilla"
                for jar in jars:
                    jar_lower = jar.lower().replace("-", "")
                    if "fabric" in jar_lower:
                        loader = "fabric"
                        break
                    if "neoforge" in jar_lower:
                        loader = "neoforge"
                        break
                    if "forge" in jar_lower:
                        loader = "forge"
                        break
                    if "quilt" in jar_lower:
                        loader = "quilt"
                        break

                evidence: dict[str, str] = {"loader_type": f"ZIP {loader}" if loader != "vanilla" else "ZIP"}
                mc_version = "unknown"
                loader_ver = "unknown"
                eula_accepted = False
                memory_max = 2048
                memory_min: int | None = None
                startup_scripts: list[str] = []
                command = ""

                for member in namelist:
                    c_name = clean_name(member)
                    c_lower = c_name.lower()
                    if c_lower == "eula.txt":
                        with suppress(Exception):
                            content = zf.read(member).decode("utf-8", errors="ignore")
                            if "eula=true" in content.lower().replace(" ", ""):
                                eula_accepted = True
                    elif c_lower in ("user_jvm_args.txt", "jvm.args"):
                        with suppress(Exception):
                            content = zf.read(member).decode("utf-8", errors="ignore")
                            memory_max = MemoryUtils.parse_memory_setting(content, "Xmx") or memory_max
                            memory_min = MemoryUtils.parse_memory_setting(content, "Xms") or memory_min
                    elif c_lower.endswith(".bat") and "/" not in c_name:
                        startup_scripts.append(c_name)
                        with suppress(Exception):
                            script_content = zf.read(member).decode("utf-8", errors="ignore")
                            if not command and "java" in script_content.lower():
                                for line in script_content.splitlines():
                                    line_strip = line.strip()
                                    if line_strip.lower().startswith("java ") or " java " in line_strip.lower():
                                        command = line_strip
                                        break
                            mem_mx = MemoryUtils.parse_memory_setting(script_content, "Xmx")
                            if mem_mx:
                                memory_max = mem_mx
                            mem_ms = MemoryUtils.parse_memory_setting(script_content, "Xms")
                            if mem_ms:
                                memory_min = mem_ms

                for jar in jars:
                    mc_match = re.search(r"(?:mc\.?|minecraft[-_]?|[-_])(1\.\d+(?:\.\d+)?)", jar, re.IGNORECASE)
                    if mc_match and mc_version == "unknown":
                        mc_version = mc_match.group(1)
                    loader_match = re.search(
                        r"(?:loader[-_.]?|forge[-_]?|fabric[-_]?|neoforge[-_]?)(\d+\.\d+(?:\.\d+)?)",
                        jar,
                        re.IGNORECASE,
                    )
                    if loader_match and loader_ver == "unknown":
                        loader_ver = loader_match.group(1)

                main_jar = jars[0] if jars else ""
                missing = []
                if not jars:
                    missing.append("server.jar 或同等主程式 JAR")
                if "eula.txt" not in [c.lower() for c in root_files]:
                    missing.append("eula.txt")
                if "server.properties" not in [c.lower() for c in root_files]:
                    missing.append("server.properties")

                if not jars and not startup_scripts:
                    warnings.append("找不到有效的伺服器檔案")
                    committable = False
                if mc_version == "unknown":
                    warnings.append("無法判斷 Minecraft 版本")

                return ServerImportInspection(
                    transaction_id=transaction_id,
                    mode=mode,
                    source_kind="archive",
                    source_path=archive_path,
                    name=name,
                    final_path=final_path,
                    loader_type=loader,
                    minecraft_version=mc_version,
                    loader_version=loader_ver,
                    memory_max_mb=memory_max,
                    memory_min_mb=memory_min,
                    eula_accepted=eula_accepted,
                    main_jar=main_jar,
                    startup_scripts=tuple(startup_scripts),
                    startup_command=command,
                    evidence=tuple(sorted((str(key), str(value)) for key, value in evidence.items())),
                    missing_files=tuple(missing),
                    warnings=tuple(warnings),
                    committable=committable,
                    conflict_type=conflict_type,
                )
        except Exception as exc:
            warnings.append(f"無法讀取 ZIP 壓縮檔：{exc}")
            return self._empty_inspection(
                archive_path,
                name,
                final_path,
                "archive",
                mode,
                warnings,
                False,
                transaction_id=transaction_id,
                conflict_type=conflict_type,
            )

    def _empty_inspection(
        self,
        source: Path,
        name: str,
        final_path: Path,
        kind: ImportSourceKind,
        mode: ImportMode,
        warnings: list[str],
        committable: bool,
        *,
        transaction_id: str | None = None,
        conflict_type: ConflictType = "none",
    ) -> ServerImportInspection:
        return ServerImportInspection(
            transaction_id=transaction_id or uuid.uuid4().hex,
            mode=mode,
            source_kind=kind,
            source_path=source,
            name=name,
            final_path=final_path,
            loader_type="unknown",
            minecraft_version="unknown",
            loader_version="unknown",
            memory_max_mb=2048,
            memory_min_mb=None,
            eula_accepted=False,
            main_jar="",
            startup_scripts=(),
            startup_command="",
            evidence=(),
            missing_files=(),
            warnings=tuple(warnings),
            committable=committable,
            conflict_type=conflict_type,
        )

    def _revalidate(self, inspection: ServerImportInspection, previous: ServerConfig | None) -> None:
        name, final_path = self._validate_name(inspection.name)
        if (
            name != inspection.name
            or final_path != inspection.final_path
            or self._root != self.server_crud.servers_root.resolve()
        ):
            raise ValueError("匯入 context 已變更，請重新檢查候選")
        if inspection.mode == "redetect":
            if previous is None or Path(previous.path).resolve(strict=False) != final_path:
                raise FileExistsError("伺服器設定已在檢查後變更")
        elif previous is not None or (final_path.exists() and inspection.source_kind != "in_place"):
            raise FileExistsError("同名伺服器已存在")
        if not inspection.source_path.exists():
            raise FileNotFoundError("匯入來源已不存在")

    @staticmethod
    def _loader_evidence(path: Path, loader: str, jars: list[str]) -> str:
        library_paths = {
            "fabric": "libraries/net/fabricmc",
            "quilt": "libraries/org/quiltmc",
            "forge": "libraries/net/minecraftforge/forge",
            "neoforge": "libraries/net/neoforged/neoforge",
        }
        library = library_paths.get(loader)
        if library and (path / library).exists():
            return f"目錄 {library}"
        match = next((jar for jar in jars if loader in jar.lower().replace("-", "")), "")
        return f"JAR {match}" if match else loader

    @staticmethod
    def _startup_scripts(path: Path) -> tuple[Path, ...]:
        managed = ServerCommands.MANAGED_STARTUP_SCRIPT_NAME.lower()
        ordered: list[Path] = []
        seen: set[Path] = set()
        for name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            candidate = path / name
            if name.lower() != managed and candidate.is_file():
                ordered.append(candidate)
                seen.add(candidate.resolve())
        for candidate in sorted(path.glob("*.bat")):
            if candidate.name.lower() == managed or candidate.resolve() in seen:
                continue
            if ServerCommands.extract_startup_script_command(candidate).has_java_command:
                ordered.append(candidate)
        managed_path = path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
        if not ordered and managed_path.is_file():
            ordered.append(managed_path)
        return tuple(ordered)

    @staticmethod
    def _first_symlink(source: Path) -> Path | None:
        if source.is_symlink():
            return source
        return next((path for path in source.rglob("*") if path.is_symlink()), None)

    def _check_disk_space(self, source: Path) -> None:
        if source.is_file():
            with zipfile.ZipFile(source) as archive:
                required = sum(info.file_size for info in archive.infolist())
        else:
            required = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
        if shutil.disk_usage(self._root).free < required:
            raise OSError(f"可用磁碟空間不足；至少需要 {required} bytes")

    def _flatten_single_wrapper(self, staging: Path) -> None:
        items = [item for item in staging.iterdir() if item.name != self._MARKER_NAME]
        if len(items) != 1 or not items[0].is_dir():
            return
        wrapper = items[0]
        for item in wrapper.iterdir():
            destination = staging / item.name
            if destination.exists() or not PathUtils.move_within(staging, item, destination):
                raise RuntimeError(f"攤平 ZIP 單層目錄失敗：{item.name}")
        wrapper.rmdir()

    def _write_marker(self, directory: Path, inspection: ServerImportInspection, state: str) -> None:
        if not atomic_write_json(
            directory / self._MARKER_NAME,
            {
                "schema_version": 1,
                "transaction_id": inspection.transaction_id,
                "name": inspection.name,
                "state": state,
                "target_config": {
                    "minecraft_version": inspection.minecraft_version,
                    "loader_type": inspection.loader_type,
                    "loader_version": inspection.loader_version,
                    "memory_max_mb": inspection.memory_max_mb,
                    "memory_min_mb": inspection.memory_min_mb,
                    "eula_accepted": inspection.eula_accepted,
                },
            },
        ):
            raise RuntimeError("無法寫入匯入 transaction marker")

    @staticmethod
    def _config_matches_marker(config: ServerConfig | None, target: Any) -> bool:
        if config is None or not isinstance(target, dict):
            return False
        return all(
            getattr(config, field) == target.get(field)
            for field in (
                "minecraft_version",
                "loader_type",
                "loader_version",
                "memory_max_mb",
                "memory_min_mb",
                "eula_accepted",
            )
        )

    def _compensate(
        self,
        inspection: ServerImportInspection,
        staging: Path,
        moved_to_final: bool,
        registered: bool,
        previous: ServerConfig | None,
        script_changed: bool,
        previous_script_existed: bool,
        previous_script: bytes | None,
    ) -> bool:
        clean = True
        if registered:
            if previous is None:
                self.server_crud.servers.pop(inspection.name, None)
            else:
                self.server_crud.servers[inspection.name] = previous
            clean = self.server_crud.write_servers_config() and clean
        if inspection.source_kind == "in_place":
            if script_changed:
                clean = self._restore_script(inspection.final_path, previous_script_existed, previous_script) and clean
            self._remove_transaction_files(inspection.final_path)
        else:
            target = inspection.final_path if moved_to_final else staging
            if target.exists():
                clean = PathUtils.delete_within(self._root, target) and clean
        return clean

    @staticmethod
    def _restore_script(path: Path, existed: bool, content: bytes | None) -> bool:
        script = path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
        try:
            if existed:
                return atomic_write_bytes(script, content or b"")
            script.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _remove_transaction_files(self, path: Path) -> None:
        for name in (self._MARKER_NAME, self._BACKUP_NAME):
            try:
                (path / name).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"無法移除匯入交易檔案 {name}: {exc}")

    @staticmethod
    def _emit(callback: ProgressCallback | None, percent: int, message: str) -> None:
        if callback is not None:
            try:
                callback(percent, message)
            except Exception as exc:
                logger.warning(f"忽略匯入 progress callback 例外: {exc}")

    @classmethod
    def _emit_units(
        cls,
        callback: ProgressCallback | None,
        done: int,
        total: int,
        start: int,
        end: int,
        message: str,
    ) -> None:
        percent = end if total <= 0 else start + int(min(1.0, done / total) * (end - start))
        cls._emit(callback, percent, message)

    @staticmethod
    def _check_cancel(cancel_check: CancelCheck) -> None:
        if cancel_check():
            raise _ImportCancelled

    def _record_diagnostic(self, inspection: ServerImportInspection, phase: str, error: Any) -> str:
        diagnostic_id = f"server-import-{inspection.transaction_id[:12]}"
        try:
            detail = self._redact_detail(
                str(error),
                inspection.name,
                str(inspection.source_path),
                str(inspection.final_path),
                str(self._root),
            )
            issues_dir = self._root / ".issues"
            issues_dir.mkdir(exist_ok=True)
            atomic_write_json(
                issues_dir / f"{diagnostic_id}.json",
                {
                    "schema_version": 1,
                    "diagnostic_id": diagnostic_id,
                    "operation": "server_import",
                    "phase": phase,
                    "error_type": type(error).__name__,
                    "detail": detail,
                    "timestamp_epoch_ms": int(time.time() * 1000),
                },
            )
        except Exception as exc:
            logger.error(f"無法寫入 server import 診斷 [{diagnostic_id}]: {exc}")
        return diagnostic_id

    @staticmethod
    def _redact_detail(detail: str, *sensitive_values: str) -> str:
        redacted = detail
        for value in filter(None, sensitive_values):
            redacted = redacted.replace(value, "<redacted>")
        return redacted


__all__ = ["ServerImportService"]
