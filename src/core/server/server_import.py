"""交易式伺服器匯入、批次探索與重新偵測"""

from __future__ import annotations

import re
import stat
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.models import (
    ConflictType,
    ImportManifest,
    ImportManifestEntry,
    ImportMode,
    ImportSourceKind,
    ProgressEvent,
    ServerConfig,
    ServerDiscoveryIssue,
    ServerDiscoveryReport,
    ServerImportBatchResult,
    ServerImportInspection,
    ServerImportResult,
    ServerInspection,
    ServerInspectionIntent,
    ServerLaunchTarget,
)
from src.utils import (
    SAFE_DIRECTORY_MAX_FILES,
    SAFE_DIRECTORY_MAX_TOTAL_BYTES,
    SAFE_HASH_FILE_MAX_BYTES,
    SAFE_TEXT_FILE_MAX_BYTES,
    SAFE_ZIP_MAX_ARCHIVE_BYTES,
    HashUtils,
    ImportCancelledError,
    MemoryUtils,
    OperationError,
    ServerCommands,
    SystemUtils,
    atomic_write_bytes,
    atomic_write_json,
    copy_dir,
    delete_within,
    find_first_reparse_point,
    get_logger,
    is_path_within,
    is_reparse_point,
    list_bounded_directory,
    move_within,
    open_bounded_zip,
    open_regular_file,
    open_regular_file_for_write,
    read_bytes_file,
    read_json,
    resolve_stable_directory,
    safe_extract_zip,
    stable_directory,
    validate_server_name,
    walk_bounded_tree,
)

from .server_crud import ServerConfigChangeSet, ServerCRUD
from .server_inspector import ServerInspector
from .server_properties_migration import ServerPropertiesMigrationService

logger = get_logger().bind(component="ServerImport")

ProgressCallback = Callable[[ProgressEvent], None]
CancelCheck = Callable[[], bool]


class ServerImportService:
    """從唯讀檢查到檔案與設定提交的唯一 owner"""

    _MARKER_NAME = ".msm-server-import.json"
    _BACKUP_NAME = ".msm-start-server.backup"
    _STAGING_GLOB = ".msm-import-*.staging"
    _IMPORT_REVISION_NAMES = frozenset(
        {
            "eula.txt",
            "jvm.args",
            "server.properties",
            "user_jvm_args.txt",
        }
    )
    _IMPORT_REVISION_SUFFIXES = frozenset(
        {
            ".bat",
            ".cmd",
            ".com",
            ".dll",
            ".exe",
            ".jar",
            ".js",
            ".kts",
            ".lua",
            ".ps1",
            ".py",
            ".sh",
            ".so",
            ".vbs",
            ".wsf",
        }
    )

    def __init__(self, server_crud: ServerCRUD, server_inspector: ServerInspector | None = None) -> None:
        self.server_crud = server_crud
        self.server_inspector = server_inspector or ServerInspector()
        self._root = resolve_stable_directory(server_crud.servers_root)
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
        raw_source = Path(source_path)
        if is_reparse_point(raw_source):
            raise ValueError("匯入來源不可為符號連結或 reparse point")
        source = raw_source.resolve(strict=True)
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

        previous = self.server_crud.snapshot().get(normalized_name)
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

        if kind in {"directory", "in_place"}:
            if kind == "directory" and (source == self._root or is_path_within(source, final_path, strict=False)):
                raise ValueError("來源不可等於伺服器根目錄或包含匯入目標")
            if kind == "directory":
                reparse_point = find_first_reparse_point(source, max_entries=SAFE_DIRECTORY_MAX_FILES)
                if reparse_point is not None:
                    raise ValueError(f"資料夾來源不可包含符號連結或 reparse point：{reparse_point.name}")

        warnings: list[str] = []
        if conflict_type == "both":
            warnings.append("同名伺服器已存在於磁碟與設定中")
        elif conflict_type == "disk":
            warnings.append("目標伺服器資料夾已存在於磁碟上")
        elif conflict_type == "config":
            warnings.append("同名伺服器已註冊於設定中")

        if kind == "archive":
            return self._inspect_archive(
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
            previous=previous,
        )

    def inspect_registered(self, name: str) -> ServerImportInspection:
        """
        唯讀檢查已註冊且位於固定 root 直接子目錄的實例

        Args:
            name: 已註冊伺服器名稱

        Returns:
            重新偵測模式的不可變候選快照
        """
        config = self.server_crud.snapshot().get(name)
        if config is None:
            raise KeyError(f"找不到伺服器設定：{name}")
        return self.inspect(config.path, name, mode="redetect")

    def discover(self) -> ServerDiscoveryReport:
        """
        探索固定 root 的直接子目錄，不切換 repository context

        Returns:
            依名稱排序的有效伺服器候選與個別失敗資訊
        """
        inspections: list[ServerImportInspection] = []
        issues: list[ServerDiscoveryIssue] = []
        managed_count = 0
        try:
            children = list_bounded_directory(self._root, reject_reparse=False)
        except OSError as e:
            return ServerDiscoveryReport(issues=(ServerDiscoveryIssue(self._root, str(e)),))
        registered_paths = {Path(config.path).resolve(strict=False) for config in self.server_crud.snapshot().values()}
        for child in sorted(children, key=lambda path: path.name.lower()):
            if child.name.startswith(".msm-") or is_reparse_point(child) or not child.is_dir():
                continue
            try:
                resolved = child.resolve(strict=True)
                if resolved.parent != self._root:
                    continue
                if resolved in registered_paths:
                    managed_count += 1
                    continue
                if not self._looks_like_server_candidate(child):
                    continue
                inspection = self.inspect(child, child.name, mode="import")
                if inspection.server.is_candidate:
                    inspections.append(inspection)
            except (OSError, ValueError) as e:
                issues.append(ServerDiscoveryIssue(child, str(e)))
        return ServerDiscoveryReport(
            candidates=tuple(inspections),
            issues=tuple(issues),
            managed_count=managed_count,
        )

    @staticmethod
    def _looks_like_server_candidate(path: Path) -> bool:
        """以根目錄特徵快速排除一般資料夾"""
        try:
            for entry in list_bounded_directory(path, max_entries=4096, reject_reparse=False):
                name = entry.name.casefold()
                if name in {"eula.txt", "server.properties", "run.bat", "start_server.bat"}:
                    return True
                if entry.is_file() and name.endswith(".jar"):
                    return True
                if entry.is_dir() and name in {"libraries", "mods", "versions"}:
                    return True
        except OSError:
            return False
        return False

    def execute(
        self,
        inspection: ServerImportInspection,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        apply_properties_migration: bool = False,
    ) -> ServerImportResult:
        """
        執行單一候選的準備、提交與失敗補償

        Args:
            inspection: 由本服務產生的不可變候選
            progress_callback: 接收百分比與狀態文字的選用回呼
            cancel_check: 回傳 True 時要求安全取消的選用回呼
            apply_properties_migration: 是否自動遷移舊版 server.properties 設定

        Returns:
            明確區分完成、略過、取消與失敗的結果
        """
        cancel = cancel_check or (lambda: False)
        if not inspection.committable:
            return ServerImportResult("skipped", "候選有名稱或路徑衝突", inspection.name, warnings=inspection.warnings)
        with self._lock:
            return self._execute_locked(
                inspection,
                progress_callback,
                cancel,
                apply_properties_migration=apply_properties_migration,
            )

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
        *,
        apply_properties_migration: bool = False,
    ) -> ServerImportResult:
        staging = self._root / f".msm-import-{inspection.transaction_id}.staging"
        work_path = inspection.source_path
        moved_to_final = False
        source_copy: Path | None = None
        registered = False
        script_changed = False
        registry_snapshot = self.server_crud.snapshot()
        previous = registry_snapshot.get(inspection.name)
        previous_script: bytes | None = None
        previous_script_existed = False
        phase = "validate"
        active = inspection
        try:
            with stable_directory(self._root) as staging_parent:
                staging = staging_parent / f".msm-import-{inspection.transaction_id}.staging"
                staging.mkdir(exist_ok=False)
            self._revalidate(inspection, previous)
            self._check_cancel(cancel_check)
            if inspection.source_kind == "in_place" and apply_properties_migration:
                self._apply_properties_migration(work_path)
            if inspection.source_kind != "in_place":
                phase = "materialize"
                self._check_disk_space(inspection)
                self._write_marker(staging, inspection, "materializing")
                if inspection.source_kind == "archive":
                    source_copy = self._materialize_verified_archive(inspection, cancel_check)
                    self._check_archive_disk_space(source_copy)
                    safe_extract_zip(
                        source_copy,
                        staging,
                        progress_callback=lambda done, total: self._emit_units(
                            progress_callback, done, total, 5, 65, "正在解壓縮伺服器..."
                        ),
                    )
                    self._flatten_single_wrapper(staging)
                elif not copy_dir(
                    inspection.source_path,
                    staging,
                    progress_callback=lambda done, total: self._emit_units(
                        progress_callback, done, total, 5, 65, "正在複製伺服器..."
                    ),
                    manifest={
                        entry.relative_path.casefold(): (entry.size, entry.mtime_ns)
                        for entry in inspection.manifest.entries
                    }
                    if inspection.manifest
                    else None,
                    cancel_check=cancel_check,
                ):
                    raise OperationError("複製伺服器資料夾失敗")
                if inspection.manifest is not None:
                    self._validate_manifest_hashes(staging, inspection.manifest)
                work_path = staging
                if apply_properties_migration:
                    self._apply_properties_migration(work_path)
                active = self._inspect_directory(
                    work_path,
                    inspection.name,
                    inspection.final_path,
                    inspection.source_kind,
                    inspection.mode,
                    transaction_id=inspection.transaction_id,
                    previous=previous,
                    build_manifest=False,
                )
                if not active.committable:
                    raise OperationError("staging 內容不是有效的 Minecraft 伺服器")
            phase = "prepare_script"
            self._check_cancel(cancel_check)
            self._emit(progress_callback, 72, "正在準備受管啟動腳本...")
            config = active.build_config(work_path, previous)
            managed_script = work_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
            if inspection.source_kind == "in_place":
                previous_script_existed = managed_script.is_file()
                previous_script = (
                    read_bytes_file(managed_script, max_bytes=SAFE_TEXT_FILE_MAX_BYTES)
                    if previous_script_existed
                    else None
                )
                if previous_script_existed and previous_script is None:
                    raise ValueError("既有受管啟動腳本超過安全大小上限或不是一般檔案")
                if previous_script_existed and not atomic_write_bytes(
                    work_path / self._BACKUP_NAME, previous_script or b""
                ):
                    raise OperationError("無法保存既有啟動腳本快照")
                self._write_marker(work_path, inspection, "script_preparing")
            override = (
                ServerCommands.ensure_nogui_in_command(
                    ServerCommands.replace_startup_command_java_path(active.server.launch_target.command, config)
                )
                if active.server.launch_target.command
                else None
            )
            if not self.server_crud.create_launch_script(
                config,
                java_command_override=override,
                launch_target=active.server.launch_target.value,
            ):
                raise OperationError("建立受管啟動腳本失敗")
            script_changed = True
            self._write_marker(work_path, inspection, "prepared")

            phase = "commit"
            self._check_cancel(cancel_check)
            self._emit(progress_callback, 88, "正在提交伺服器實例...")
            if inspection.source_kind != "in_place":
                if inspection.final_path.exists():
                    raise FileExistsError("匯入目標在提交前已存在")
                if not move_within(self._root, staging, inspection.final_path):
                    raise OSError("無法將匯入 staging 移至伺服器目標")
                moved_to_final = True
                work_path = inspection.final_path
                config.path = str(work_path)
                self._write_marker(work_path, inspection, "moved")
            commit_result = self.server_crud.commit(
                ServerConfigChangeSet(upserts=(config,)),
                expected_revision=registry_snapshot.revision,
            )
            if not commit_result.success:
                raise OperationError(commit_result.message or "儲存 servers_config.json 失敗")
            registered = True
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
                evidence=active.server.evidence,
            )
        except ImportCancelledError:
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
        except FileExistsError as e:
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
            return ServerImportResult("skipped", str(e), inspection.name, cleanup_complete=cleanup)
        except Exception as e:
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
            diagnostic_id = self._record_diagnostic(inspection, phase, e)
            logger.exception(f"伺服器匯入交易失敗 [{diagnostic_id}]: {e}")
            return ServerImportResult(
                "failed",
                f"匯入失敗；診斷編號：{diagnostic_id}",
                inspection.name,
                diagnostic_id=diagnostic_id,
                cleanup_complete=cleanup,
            )
        finally:
            if source_copy is not None:
                delete_within(self._root, source_copy)

    def _materialize_verified_archive(
        self,
        inspection: ServerImportInspection,
        cancel_check: CancelCheck,
    ) -> Path:
        """將已核准的 ZIP 固定為受管理的私有副本"""
        source_copy = self._root / f".msm-import-{inspection.transaction_id}.source.zip"
        hasher = HashUtils.new_hasher("sha256")
        if hasher is None:
            raise ValueError("無法建立 ZIP 雜湊器")
        total = 0
        try:
            with (
                open_regular_file(inspection.source_path) as source,
                open_regular_file_for_write(source_copy) as target,
            ):
                while chunk := source.read(1024 * 1024):
                    self._check_cancel(cancel_check)
                    total += len(chunk)
                    if total > SAFE_ZIP_MAX_ARCHIVE_BYTES:
                        raise ValueError("匯入 ZIP 超過安全大小上限")
                    hasher.update(chunk)
                    target.write(chunk)
                target.flush()
            if hasher.hexdigest() != inspection.server.revision:
                raise ValueError("匯入來源已在檢查後變更，請重新檢查候選")
            return source_copy
        except Exception:
            delete_within(self._root, source_copy)
            raise

    def _check_archive_disk_space(self, source: Path) -> None:
        with open_bounded_zip(source) as archive:
            required = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                required += max(0, int(info.file_size))
                if required > SAFE_DIRECTORY_MAX_TOTAL_BYTES:
                    raise ValueError(f"匯入內容解壓後大小超過安全上限 {SAFE_DIRECTORY_MAX_TOTAL_BYTES} bytes")
        if SystemUtils.get_free_disk_bytes(self._root) < required:
            raise OSError(f"可用磁碟空間不足；至少需要 {required} bytes")

    def recover_orphans(self) -> None:
        """清理 crash staging，並完成或回復帶 marker 的實例"""
        with self._lock:
            try:
                root_entries = list_bounded_directory(self._root, reject_reparse=False)
            except OSError:
                return
            for staging in root_entries:
                if not (staging.name.startswith(".msm-import-") and staging.name.endswith(".staging")):
                    continue
                if not is_reparse_point(staging) and staging.is_dir():
                    delete_within(self._root, staging)
            for source_copy in root_entries:
                if not (source_copy.name.startswith(".msm-import-") and source_copy.name.endswith(".source.zip")):
                    continue
                if not is_reparse_point(source_copy) and source_copy.is_file():
                    delete_within(self._root, source_copy)
            for candidate in root_entries:
                marker = candidate / self._MARKER_NAME
                if is_reparse_point(candidate) or not candidate.is_dir() or not marker.is_file():
                    continue
                state = ""
                payload: dict[str, Any] = {}
                try:
                    loaded = read_json(marker, {}) or {}
                    if isinstance(loaded, dict):
                        payload = loaded
                    state = str(payload.get("state", ""))
                except Exception as e:
                    logger.warning(f"無法解析匯入交易 marker {marker}: {e}")
                config = self.server_crud.snapshot().get(candidate.name)
                registered = config is not None and Path(config.path).resolve(strict=False) == candidate.resolve()
                source_kind = str(payload.get("source_kind", ""))
                if state == "committed" and registered:
                    self._remove_transaction_files(candidate)
                elif (candidate / self._BACKUP_NAME).is_file():
                    target = payload.get("target_config", {}) if isinstance(payload, dict) else {}
                    if not registered or not self._config_matches_marker(config, target):
                        previous_script = read_bytes_file(
                            candidate / self._BACKUP_NAME,
                            max_bytes=SAFE_TEXT_FILE_MAX_BYTES,
                        )
                        if previous_script is not None:
                            self._restore_script(candidate, True, previous_script)
                        else:
                            logger.error(f"無法復原超過安全大小上限的啟動腳本快照: {candidate.name}")
                    self._remove_transaction_files(candidate)
                elif not registered:
                    if source_kind in {"archive", "directory"}:
                        delete_within(self._root, candidate)
                    else:
                        if source_kind == "in_place" and state in {"script_preparing", "prepared"}:
                            self._restore_script(candidate, False, None)
                        self._remove_transaction_files(candidate)
                else:
                    self._remove_transaction_files(candidate)

    def _validate_name(self, name: str) -> tuple[str, Path]:
        normalized = validate_server_name(name)
        final_path = (self._root / normalized).resolve(strict=False)
        if final_path.parent != self._root or not is_path_within(self._root, final_path, strict=False):
            raise ValueError("無效的伺服器名稱（路徑穿越偵測）")
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
        previous: ServerConfig | None = None,
        build_manifest: bool = True,
    ) -> ServerImportInspection:
        intent = self._inspection_intent(mode, previous)
        server = self.server_inspector.inspect(path, intent)
        manifest: ImportManifest | None = None
        if kind == "directory" and server.revision and build_manifest:
            manifest = self._build_directory_manifest(path)
            if manifest is None:
                error = "無法建立匯入來源內容完整性快照"
                server = replace(
                    server,
                    revision="",
                    is_candidate=False,
                    status_ready=False,
                    launchable=False,
                    error=error,
                    warnings=(*server.warnings, error),
                )
            else:
                server = replace(server, revision=manifest.revision)
        warnings = [*(extra_warnings or []), *server.warnings]
        return ServerImportInspection(
            transaction_id=transaction_id,
            mode=mode,
            source_kind=kind,
            source_path=path,
            name=name,
            final_path=final_path,
            server=server,
            warnings=tuple(dict.fromkeys(warnings)),
            committable=committable and server.is_candidate,
            conflict_type=conflict_type,
            manifest=manifest,
        )

    def _inspect_archive(
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
        warnings = list(extra_warnings or [])
        try:
            with open_bounded_zip(archive_path) as archive:
                files = [info for info in archive.infolist() if not info.is_dir()]
                parts = [Path(info.filename.replace("\\", "/")).parts for info in files]
                wrapper = (
                    parts[0][0] if parts and all(len(value) > 1 and value[0] == parts[0][0] for value in parts) else ""
                )
                entries: dict[str, Any] = {}
                for info, value in zip(files, parts, strict=True):
                    relative_parts = value[1:] if wrapper else value
                    entries["/".join(relative_parts).casefold()] = info

                jar_names = [Path(value).name for value in entries if "/" not in value and value.endswith(".jar")]
                combined = "\n".join(entries)
                loader_type = "vanilla"
                for loader in ("neoforge", "quilt", "fabric", "forge"):
                    if loader in combined:
                        loader_type = loader
                        break
                minecraft_version = "unknown"
                loader_version = "unknown" if loader_type != "vanilla" else ""
                patterns = (
                    r"mc[.-]?(\d+\.\d+(?:\.\d+)?)-loader[.-]?(\d+(?:\.\d+)+)",
                    r"(?:forge|neoforge)[.-](\d+\.\d+(?:\.\d+)?)[.-](\d+(?:\.\d+)+)",
                )
                for pattern in patterns:
                    if match := re.search(pattern, combined, re.IGNORECASE):
                        minecraft_version, loader_version = match.group(1), match.group(2)
                        break

                script_name = next(
                    (
                        candidate
                        for candidate in ServerCommands.STARTUP_SCRIPT_CANDIDATES
                        if candidate.casefold() in entries
                    ),
                    "",
                )
                startup_command = ""
                memory_max_mb = 2048
                memory_min_mb: int | None = None
                if script_name:
                    info = entries[script_name.casefold()]
                    if info.file_size <= SAFE_TEXT_FILE_MAX_BYTES:
                        text = archive.read(info).decode("utf-8-sig", errors="replace")
                        for line in text.splitlines():
                            normalized = ServerCommands.normalize_imported_java_command(line.strip())
                            if normalized:
                                startup_command = normalized
                                memory_max_mb = MemoryUtils.parse_memory_setting(line, "Xmx") or memory_max_mb
                                memory_min_mb = MemoryUtils.parse_memory_setting(line, "Xms")
                                break
                launch_target = (
                    ServerLaunchTarget("script", script_name, startup_command, tuple(jar_names), "ZIP 啟動腳本")
                    if startup_command
                    else ServerLaunchTarget(
                        "jar",
                        jar_names[0] if jar_names else "",
                        candidates=tuple(jar_names),
                        reason="ZIP 根目錄 JAR",
                    )
                )
                eula_state = "missing"
                if (
                    eula_info := entries.get("eula.txt")
                ) is not None and eula_info.file_size <= SAFE_TEXT_FILE_MAX_BYTES:
                    eula_text = archive.read(eula_info).decode("utf-8", errors="replace")
                    eula_state = "accepted" if re.search(r"(?im)^\s*eula\s*=\s*true\s*$", eula_text) else "rejected"
                is_candidate = bool(jar_names and launch_target.value)
                server_warnings = []
                if minecraft_version == "unknown":
                    server_warnings.append("無法從 ZIP 檔名判斷 Minecraft 版本，匯入後會再次檢測")
                server = ServerInspection(
                    path=archive_path,
                    revision=self._archive_revision(archive_path),
                    is_candidate=is_candidate,
                    error="" if is_candidate else "ZIP 內找不到有效的伺服器檔案",
                    loader_type=loader_type,
                    minecraft_version=minecraft_version,
                    loader_version=loader_version,
                    evidence=(("archive", "ZIP 中央目錄與啟動腳本"),),
                    launch_target=launch_target,
                    memory_max_mb=memory_max_mb,
                    memory_min_mb=memory_min_mb,
                    eula_state=eula_state,
                    warnings=tuple(server_warnings),
                    status_ready=is_candidate and eula_state == "accepted",
                    launchable=is_candidate,
                )
                return ServerImportInspection(
                    transaction_id,
                    mode,
                    "archive",
                    archive_path,
                    name,
                    final_path,
                    server,
                    tuple(dict.fromkeys([*warnings, *server_warnings])),
                    committable and is_candidate,
                    conflict_type,
                )
        except Exception as e:
            warnings.append(f"無法讀取 ZIP 壓縮檔：{e}")
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

    @staticmethod
    def _inspection_intent(mode: ImportMode, previous: ServerConfig | None) -> ServerInspectionIntent:
        return ServerInspectionIntent(
            purpose=mode,
            expected_loader_type=previous.loader_type if previous else "",
            expected_minecraft_version=previous.minecraft_version if previous else "",
            expected_loader_version=previous.loader_version if previous else "",
        )

    @staticmethod
    def _archive_revision(archive_path: Path) -> str:
        """以受限檔案雜湊建立匯入來源 revision"""
        digest = HashUtils.compute_file_hash_sync(
            archive_path,
            "sha256",
            max_bytes=SAFE_ZIP_MAX_ARCHIVE_BYTES,
        )
        if not digest:
            raise ValueError(f"ZIP 檔案無法在安全上限內計算雜湊：{archive_path.name}")
        return digest

    @classmethod
    def _build_directory_manifest(cls, path: Path) -> ImportManifest | None:
        """建立可供複製階段重用的匯入來源清單"""
        digest = HashUtils.new_hasher("sha256")
        entries: list[ImportManifestEntry] = []
        total_bytes = 0
        try:
            for root_path, dirs, files in walk_bounded_tree(path, max_entries=SAFE_DIRECTORY_MAX_FILES):
                relative_root = root_path.relative_to(path)
                for directory_name in dirs:
                    relative = (relative_root / directory_name).as_posix().casefold()
                    digest.update(f"D:{relative}\n".encode())
                for file_name in files:
                    if file_name.casefold() in {cls._MARKER_NAME, cls._BACKUP_NAME}:
                        continue
                    file_path = root_path / file_name
                    metadata = file_path.stat(follow_symlinks=False)
                    relative_path = (relative_root / file_name).as_posix()
                    relative_key = relative_path.casefold()
                    digest.update(f"F:{relative_key}:{metadata.st_size}:{metadata.st_mtime_ns}".encode())
                    file_digest = ""
                    if (
                        file_name.casefold() in cls._IMPORT_REVISION_NAMES
                        or file_path.suffix.casefold() in cls._IMPORT_REVISION_SUFFIXES
                    ):
                        file_digest = HashUtils.compute_file_hash_sync(
                            file_path,
                            "sha256",
                            max_bytes=SAFE_HASH_FILE_MAX_BYTES,
                            allowed_root=path,
                        )
                        if not file_digest:
                            return None
                        digest.update(b":H:")
                        digest.update(file_digest.encode("ascii"))
                    digest.update(b"\n")
                    total_bytes += metadata.st_size
                    if total_bytes > SAFE_DIRECTORY_MAX_TOTAL_BYTES:
                        return None
                    entries.append(
                        ImportManifestEntry(
                            relative_path,
                            metadata.st_size,
                            metadata.st_mtime_ns,
                            file_digest,
                        )
                    )
        except (OSError, ValueError) as e:
            logger.warning(f"建立匯入來源內容 revision 失敗 {path}: {e}")
            return None
        return ImportManifest(tuple(entries), digest.hexdigest(), total_bytes)

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
        server = ServerInspection(
            path=source,
            revision="",
            is_candidate=False,
            error=warnings[-1] if warnings else "無法檢查伺服器",
            warnings=tuple(warnings),
        )
        return ServerImportInspection(
            transaction_id=transaction_id or uuid.uuid4().hex,
            mode=mode,
            source_kind=kind,
            source_path=source,
            name=name,
            final_path=final_path,
            server=server,
            warnings=tuple(warnings),
            committable=committable,
            conflict_type=conflict_type,
        )

    def _revalidate(self, inspection: ServerImportInspection, previous: ServerConfig | None) -> None:
        name, final_path = self._validate_name(inspection.name)
        if (
            name != inspection.name
            or final_path != inspection.final_path
            or self._root != resolve_stable_directory(self.server_crud.servers_root)
        ):
            raise ValueError("匯入 context 已變更，請重新檢查候選")
        if inspection.mode == "redetect":
            if previous is None or Path(previous.path).resolve(strict=False) != final_path:
                raise FileExistsError("伺服器設定已在檢查後變更")
        elif previous is not None or (final_path.exists() and inspection.source_kind != "in_place"):
            raise FileExistsError("同名伺服器已存在")
        if is_reparse_point(inspection.source_path):
            raise ValueError("匯入來源在執行前變成符號連結或 reparse point")
        if not inspection.source_path.exists():
            raise FileNotFoundError("匯入來源已不存在")
        if inspection.source_kind == "archive":
            current_revision = self._archive_revision(inspection.source_path)
        elif inspection.source_kind == "directory":
            current_manifest = self._build_directory_manifest(inspection.source_path)
            if current_manifest is None:
                raise ValueError("匯入來源無法重新建立內容完整性快照")
            current_revision = current_manifest.revision
        else:
            current_revision = self.server_inspector.inspect(
                inspection.source_path,
                self._inspection_intent(inspection.mode, previous),
            ).revision
        if current_revision != inspection.server.revision:
            raise ValueError("匯入來源已在檢查後變更，請重新檢查候選")

    def _check_disk_space(self, inspection: ServerImportInspection) -> None:
        source = inspection.source_path
        if source.is_file():
            self._check_archive_disk_space(source)
            return
        required = inspection.manifest.total_bytes if inspection.manifest is not None else 0
        file_count = 0
        try:
            if inspection.manifest is not None:
                file_count = len(inspection.manifest.entries)
            else:
                for root_path, _dirs, files in walk_bounded_tree(source):
                    for name in files:
                        candidate = root_path / name
                        metadata = candidate.stat(follow_symlinks=False)
                        if not stat.S_ISREG(metadata.st_mode):
                            raise ValueError(f"匯入來源不是一般檔案：{candidate.name}")
                        file_count += 1
                        if file_count > SAFE_DIRECTORY_MAX_FILES:
                            raise ValueError(f"匯入來源檔案數超過安全上限 {SAFE_DIRECTORY_MAX_FILES}")
                        required += max(0, metadata.st_size)
                        if required > SAFE_DIRECTORY_MAX_TOTAL_BYTES:
                            raise ValueError(f"匯入內容大小超過安全上限 {SAFE_DIRECTORY_MAX_TOTAL_BYTES} bytes")
        except (OSError, ValueError) as e:
            raise ValueError(f"匯入來源不可安全巡覽：{e}") from e
        if SystemUtils.get_free_disk_bytes(self._root) < required:
            raise OSError(f"可用磁碟空間不足；至少需要 {required} bytes")

    @classmethod
    def _validate_manifest_hashes(cls, staging: Path, manifest: ImportManifest) -> None:
        """驗證複製後所有具備雜湊的檔案內容"""
        for entry in manifest.entries:
            if not entry.sha256:
                continue
            target_file = staging / entry.relative_path
            digest = HashUtils.compute_file_hash_sync(
                target_file,
                "sha256",
                max_bytes=SAFE_HASH_FILE_MAX_BYTES,
                allowed_root=staging,
            )
            if digest != entry.sha256:
                raise ValueError(f"匯入來源在複製期間變更：{entry.relative_path}")

    def _flatten_single_wrapper(self, staging: Path) -> None:
        items = [item for item in list_bounded_directory(staging) if item.name != self._MARKER_NAME]
        if len(items) != 1 or not items[0].is_dir():
            return
        wrapper = items[0]
        for item in list_bounded_directory(wrapper):
            destination = staging / item.name
            if destination.exists() or not move_within(staging, item, destination):
                raise OperationError(f"攤平 ZIP 單層目錄失敗：{item.name}")
        if not delete_within(staging, wrapper):
            raise OperationError("攤平 ZIP 單層目錄後無法安全清除空資料夾")

    def _write_marker(self, directory: Path, inspection: ServerImportInspection, state: str) -> None:
        if not atomic_write_json(
            directory / self._MARKER_NAME,
            {
                "schema_version": 1,
                "transaction_id": inspection.transaction_id,
                "name": inspection.name,
                "state": state,
                "source_kind": inspection.source_kind,
                "target_config": {
                    "minecraft_version": inspection.server.minecraft_version,
                    "loader_type": inspection.server.loader_type,
                    "loader_version": inspection.server.loader_version,
                    "memory_max_mb": inspection.server.memory_max_mb,
                    "memory_min_mb": inspection.server.memory_min_mb,
                },
            },
        ):
            raise OperationError("無法寫入匯入 transaction marker")

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
            current = self.server_crud.snapshot()
            rollback = (
                ServerConfigChangeSet(removals=(inspection.name,))
                if previous is None
                else ServerConfigChangeSet(upserts=(previous,))
            )
            rollback_result = self.server_crud.commit(rollback, expected_revision=current.revision)
            clean = rollback_result.success and clean
        if inspection.source_kind == "in_place":
            if script_changed:
                clean = self._restore_script(inspection.final_path, previous_script_existed, previous_script) and clean
            self._remove_transaction_files(inspection.final_path)
        else:
            target = inspection.final_path if moved_to_final else staging
            if target.exists():
                clean = delete_within(self._root, target) and clean
        return clean

    @staticmethod
    def _restore_script(path: Path, existed: bool, content: bytes | None) -> bool:
        script = path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
        try:
            if existed:
                return atomic_write_bytes(script, content or b"")
            return delete_within(path, script)
        except OSError:
            return False

    def _remove_transaction_files(self, path: Path) -> None:
        for name in (self._MARKER_NAME, self._BACKUP_NAME):
            try:
                delete_within(path, path / name)
            except OSError as e:
                logger.warning(f"無法移除匯入交易檔案 {name}: {e}")

    @staticmethod
    def _apply_properties_migration(work_path: Path) -> None:
        """
        若存在 server.properties 且有遷移項目，套用遷移並建立備份
        """
        try:
            plan = ServerPropertiesMigrationService.inspect_source(work_path)
            if plan is not None and plan.needs_migration:
                ServerPropertiesMigrationService.apply_migration_to_directory(work_path, plan, create_backup=True)
        except Exception as e:
            logger.warning(f"套用 server.properties 遷移失敗: {e}")

    @staticmethod
    def _emit(callback: ProgressCallback | None, percent: int, message: str) -> None:
        if callback is not None:
            try:
                callback(ProgressEvent("import", message, overall_percent=percent))
            except Exception as e:
                logger.warning(f"忽略匯入 progress callback 例外: {e}")

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
        percent = None if total <= 0 else start + min(1.0, done / total) * (end - start)
        if callback is not None:
            try:
                callback(ProgressEvent("materialize", message, done, total or None, percent))
            except Exception as e:
                logger.warning(f"忽略匯入 progress callback 例外: {e}")

    @staticmethod
    def _check_cancel(cancel_check: CancelCheck) -> None:
        if cancel_check():
            raise ImportCancelledError

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
            issues_dir = resolve_stable_directory(self._root / ".issues", create=True)
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
        except Exception as e:
            logger.error(f"無法寫入 server import 診斷 [{diagnostic_id}]: {e}")
        return diagnostic_id

    @staticmethod
    def _redact_detail(detail: str, *sensitive_values: str) -> str:
        redacted = detail
        for value in filter(None, sensitive_values):
            redacted = redacted.replace(value, "<redacted>")
        return redacted


__all__ = ["ServerImportService"]
