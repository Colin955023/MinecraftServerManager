"""以 staging、單一 commit point 與統一補償建立伺服器實例"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from src.models import (
    ProgressEvent,
    ServerConfig,
    ServerCreationPlan,
    ServerCreationResult,
    ServerCreationWarning,
)
from src.utils import (
    CreationCancelledError,
    HashUtils,
    OperationError,
    ServerCommands,
    SystemUtils,
    atomic_write_json,
    delete_within,
    get_logger,
    is_path_within,
    list_bounded_directory,
    move_within,
    resolve_stable_directory,
    validate_server_name,
)

from .server_crud import ServerConfigChangeSet, ServerCRUD
from .server_inspector import ServerInspector
from .server_properties import ServerPropertiesStore

logger = get_logger().bind(component="ServerCreation")

ProgressCallback = Callable[[ProgressEvent], None]
CancelCheck = Callable[[], bool]

_CREATION_PROGRESS_RANGES: dict[str, tuple[float, float]] = {
    "server_download": (10.0, 65.0),
    "vanilla_download": (10.0, 40.0),
    "installer_download": (40.0, 65.0),
    "installer": (65.0, 90.0),
}
_CREATION_PROGRESS_ANCHORS: dict[str, float] = {
    "vanilla_prepare": 10.0,
    "server_download": 10.0,
    "vanilla_download": 10.0,
    "installer_download": 40.0,
    "installer": 65.0,
    "installer_cleanup": 90.0,
}


@dataclass(frozen=True, slots=True)
class ServerCreationConfirmation:
    """建立計畫提供給 UI 的精確、不可變確認投影"""

    name: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None
    warnings: tuple[str, ...]
    java_executable: str
    jvm_args: tuple[str, ...]
    launch_target: str
    command: tuple[str, ...]


def _has_verified_installer(artifact: Any) -> bool:
    return HashUtils.is_valid_expected_hash(
        getattr(artifact, "expected_hash", ""),
        getattr(artifact, "hash_algorithm", ""),
    )


class ServerInstallerPort(Protocol):
    """
    伺服器建立流程所需的載入器安裝與成品解析介面
    """

    def resolve_installer_artifact(self, loader_type: str, minecraft_version: str, loader_version: str) -> Any: ...

    def download_server_jar_with_progress(
        self,
        loader_type: str,
        minecraft_version: str,
        loader_version: str,
        target_path: str,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        user_java_path: str | None = None,
        *,
        installer_artifact: Any | None = None,
    ) -> bool: ...


class CreateServerJourney:
    """伺服器建立流程與交易提交的唯一外部介面"""

    _MARKER_NAME = ".msm-server-creation.json"
    _STAGING_GLOB = ".msm-create-*.staging"

    def __init__(
        self,
        server_crud: ServerCRUD,
        loader_manager: ServerInstallerPort,
        server_properties: ServerPropertiesStore | None = None,
    ) -> None:
        self.server_crud = server_crud
        self.loader_manager = loader_manager
        self.server_properties = server_properties or ServerPropertiesStore(server_crud)
        self._root = server_crud.servers_root.resolve()
        self._lock = server_crud.operation_lock
        self._recover_orphans()

    def plan(
        self,
        config: ServerConfig,
        *,
        user_java_path: str | None = None,
    ) -> ServerCreationPlan:
        """
        驗證輸入並建立不會寫入磁碟的交易計畫

        Args:
            config: 使用者選定的伺服器設定
            user_java_path: 選用的 Java 執行檔路徑

        Returns:
            包含 staging、artifact 與警告資訊的不可變計畫
        """
        name = validate_server_name(config.name)
        root = self._root
        final_path = (root / name).resolve(strict=False)
        if final_path.parent != root or not is_path_within(root, final_path, strict=False):
            raise ValueError("無效的伺服器名稱（路徑穿越偵測）")
        registry_snapshot = self.server_crud.snapshot()
        if name in registry_snapshot or final_path.exists():
            raise FileExistsError("同名伺服器已存在")

        loader_type = str(config.loader_type or "").strip().lower()
        minecraft_version = str(config.minecraft_version or "").strip()
        loader_version = str(config.loader_version or "").strip()
        if not loader_type or loader_type == "unknown":
            raise ValueError("Loader 類型不可為空或 unknown")
        if not minecraft_version or minecraft_version == "unknown":
            raise ValueError("Minecraft 版本不可為空或 unknown")
        if loader_type != "vanilla" and (not loader_version or loader_version == "unknown"):
            raise ValueError("此 Loader 必須指定版本")
        if int(config.memory_max_mb) < 1024:
            raise ValueError("最大記憶體不可低於 1024 MB")
        if config.memory_min_mb is not None and not 0 < int(config.memory_min_mb) <= int(config.memory_max_mb):
            raise ValueError("最小記憶體必須大於 0 且不可超過最大記憶體")

        normalized_java_path = str(user_java_path or "").strip() or None
        if normalized_java_path and not Path(normalized_java_path).is_file():
            raise ValueError("指定的 Java 執行檔不存在")

        artifact = self.loader_manager.resolve_installer_artifact(
            loader_type,
            minecraft_version,
            loader_version,
        )
        if loader_type != "vanilla" and not _has_verified_installer(artifact):
            raise ValueError(f"{loader_type} installer 缺少可驗證的 SHA-1、SHA-256 或 SHA-512 摘要")
        warnings: list[ServerCreationWarning] = []
        total_memory_mb = SystemUtils.get_total_memory_mb()
        if total_memory_mb > 0 and int(config.memory_max_mb) >= total_memory_mb:
            warnings.append(
                ServerCreationWarning(
                    message=f"最大記憶體 {int(config.memory_max_mb)} MB 已達或超過系統總記憶體 {total_memory_mb} MB",
                )
            )
        transaction_id = uuid.uuid4().hex
        projection_config = replace(
            config,
            name=name,
            minecraft_version=minecraft_version,
            loader_type=loader_type,
            loader_version=loader_version,
            memory_max_mb=int(config.memory_max_mb),
            memory_min_mb=int(config.memory_min_mb) if config.memory_min_mb is not None else None,
            path=str(final_path),
            jvm_args=list(config.jvm_args),
        )
        launch_target = ServerCommands.expected_main_target(loader_type, minecraft_version, loader_version)
        command_value = ServerCommands.build_java_command(
            projection_config,
            return_list=True,
            launch_target=launch_target,
        )
        command = [str(value) for value in command_value] if isinstance(command_value, list) else []
        if normalized_java_path and command:
            command[0] = normalized_java_path
        confirmation = ServerCreationConfirmation(
            name=name,
            minecraft_version=minecraft_version,
            loader_type=loader_type,
            loader_version=loader_version,
            memory_max_mb=int(config.memory_max_mb),
            memory_min_mb=int(config.memory_min_mb) if config.memory_min_mb is not None else None,
            warnings=tuple(warning.message for warning in warnings),
            java_executable=command[0] if command else (normalized_java_path or ""),
            jvm_args=tuple(command[1:]),
            launch_target=launch_target,
            command=tuple(command),
        )
        return ServerCreationPlan(
            transaction_id=transaction_id,
            name=name,
            minecraft_version=minecraft_version,
            loader_type=loader_type,
            loader_version=loader_version,
            memory_max_mb=int(config.memory_max_mb),
            memory_min_mb=int(config.memory_min_mb) if config.memory_min_mb is not None else None,
            jvm_args=tuple(str(arg) for arg in config.jvm_args),
            properties=(),
            final_path=final_path,
            staging_path=root / f".msm-create-{transaction_id}.staging",
            user_java_path=normalized_java_path,
            installer_artifact=artifact,
            warnings=tuple(warnings),
            registry_revision=registry_snapshot.revision,
            confirmation=confirmation,
        )

    def execute(
        self,
        plan: ServerCreationPlan,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ServerCreationResult:
        """
        執行建立計畫並在失敗時補償已寫入資源

        Args:
            plan: 已完成驗證的建立計畫
            progress_callback: 接收進度百分比與文字的回呼
            cancel_check: 回傳是否要求取消的檢查函式

        Returns:
            明確區分完成、取消、失敗與需確認的結果
        """
        if plan.loader_type != "vanilla" and not _has_verified_installer(plan.installer_artifact):
            return ServerCreationResult("failed", "Loader installer 缺少可驗證的完整性摘要")
        cancel_check = cancel_check or (lambda: False)
        with self._lock:
            return self._execute_locked(plan, progress_callback, cancel_check)

    def _execute_locked(
        self,
        plan: ServerCreationPlan,
        progress_callback: ProgressCallback | None,
        cancel_check: CancelCheck,
    ) -> ServerCreationResult:
        config = plan.build_config(plan.staging_path)
        moved_to_final = False
        user_facing_failure = ""
        registry_snapshot = self.server_crud.snapshot()
        try:
            phase = "validate"
            self._check_disk_space()
            self._check_cancel(cancel_check)
            if self.server_crud.servers_root.resolve() != self._root:
                raise OperationError("伺服器根目錄已變更，建立計畫已失效")
            if plan.final_path.parent != self._root or plan.staging_path.parent != self._root:
                raise ValueError("建立計畫路徑不屬於目前伺服器根目錄")
            if plan.registry_revision and registry_snapshot.revision != plan.registry_revision:
                raise OperationError("伺服器設定已變更，建立計畫已失效")
            if plan.final_path.exists() or plan.name in registry_snapshot:
                raise FileExistsError("同名伺服器已存在，建立計畫已失效")
            if plan.staging_path.exists():
                raise FileExistsError("交易 staging 路徑已存在")

            phase = "stage"
            self._emit(progress_callback, ProgressEvent("stage", "正在準備交易暫存目錄...", overall_percent=2))
            resolve_stable_directory(plan.staging_path, create=True)
            self._write_marker(plan.staging_path, plan, "staging")
            self.server_crud.prepare_server_files(config)
            initial_properties = dict(plan.properties)
            initial_properties["motd"] = f"Minecraft 伺服器 - {config.name}"
            self.server_properties.initialize(plan.staging_path, initial_properties)
            self._check_cancel(cancel_check)

            phase = "artifact"
            last_loader_message = ""
            last_overall_progress = 8.0
            self._emit(
                progress_callback,
                ProgressEvent("artifact", "正在下載並驗證伺服器檔案...", overall_percent=last_overall_progress),
            )

            def loader_progress(event: ProgressEvent) -> None:
                nonlocal last_loader_message, last_overall_progress
                last_loader_message = event.message.strip()
                phase_percent = event.phase_percent
                if phase_percent is not None:
                    start, end = _CREATION_PROGRESS_RANGES.get(event.phase, (last_overall_progress, 90.0))
                    overall = start + phase_percent / 100.0 * max(0.0, end - start)
                else:
                    overall = _CREATION_PROGRESS_ANCHORS.get(event.phase, last_overall_progress)
                last_overall_progress = max(last_overall_progress, min(90.0, overall))
                self._emit(
                    progress_callback,
                    ProgressEvent(
                        event.phase,
                        event.message,
                        event.completed_units,
                        event.total_units,
                        last_overall_progress,
                    ),
                )

            download_result = self.loader_manager.download_server_jar_with_progress(
                plan.loader_type,
                plan.minecraft_version,
                plan.loader_version,
                str(plan.staging_path / "server.jar"),
                loader_progress,
                cancel_check,
                plan.user_java_path,
                installer_artifact=plan.installer_artifact,
            )
            self._check_cancel(cancel_check)
            if not download_result:
                user_facing_failure = last_loader_message or "下載、checksum 驗證或 Loader installer 執行失敗"
                raise OperationError(user_facing_failure)

            phase = "launch_script"
            self._emit(
                progress_callback,
                ProgressEvent("launch_script", "正在建立啟動腳本...", overall_percent=92),
            )
            staged_config = replace(config, path=str(plan.staging_path), jvm_args=list(config.jvm_args))
            detected_target = ServerInspector.find_main_jar(plan.staging_path, config.loader_type, staged_config)
            confirmation = plan.confirmation
            is_legacy_forge_target = (
                confirmation is not None
                and config.loader_type.lower() == "forge"
                and (
                    confirmation.launch_target == "forge-server.jar"
                    or (
                        "forge" in confirmation.launch_target.lower()
                        and confirmation.launch_target.lower().endswith(".jar")
                    )
                )
                and "forge" in detected_target.lower()
                and detected_target.lower().endswith(".jar")
            )
            if (
                confirmation is not None
                and detected_target != confirmation.launch_target
                and not is_legacy_forge_target
            ):
                raise OperationError(
                    f"安裝後啟動目標與確認計畫不一致：{detected_target} != {confirmation.launch_target}"
                )
            if not self.server_crud.create_launch_script(staged_config, launch_target=detected_target):
                raise OperationError("建立啟動腳本失敗")
            ServerCommands.cleanup_redundant_startup_scripts(plan.staging_path)
            self._validate_staged_instance(plan)
            self._check_cancel(cancel_check)
            self._write_marker(plan.staging_path, plan, "prepared")

            phase = "commit"
            self._emit(progress_callback, ProgressEvent("commit", "正在提交伺服器實例...", overall_percent=96))
            if not move_within(self._root, plan.staging_path, plan.final_path):
                raise OSError("無法安全提交伺服器 staging 目錄")
            moved_to_final = True
            config.path = str(plan.final_path)
            ServerCommands.cleanup_redundant_startup_scripts(plan.final_path)
            if (plan.final_path / "user_jvm_args.txt").is_file():
                ServerCommands.update_forge_user_jvm_args(plan.final_path, config)
            self._write_marker(plan.final_path, plan, "moved")
            commit_result = self.server_crud.commit(
                ServerConfigChangeSet(upserts=(config,)),
                expected_revision=registry_snapshot.revision,
            )
            if not commit_result.success:
                raise OperationError(commit_result.message or "儲存 servers_config.json 失敗")
            marker = plan.final_path / self._MARKER_NAME
            try:
                delete_within(plan.final_path, marker)
            except OSError as e:
                logger.warning(f"已提交實例但無法移除 transaction marker: {e}")
            self._emit(progress_callback, ProgressEvent("completed", "伺服器建立完成！", 1, 1, 100))
            return ServerCreationResult("completed", f"伺服器 {plan.name} 已建立", config=config)
        except CreationCancelledError:
            cleanup_complete = self._compensate(plan, moved_to_final)
            diagnostic_id = self._record_diagnostic(plan, phase, "cancelled")
            return ServerCreationResult(
                "cancelled",
                "使用者已取消建立伺服器",
                diagnostic_id=diagnostic_id,
                cleanup_complete=cleanup_complete,
            )
        except Exception as e:
            cleanup_complete = self._compensate(plan, moved_to_final)
            diagnostic_id = self._record_diagnostic(plan, phase, e)
            logger.exception(f"伺服器建立交易失敗 [{diagnostic_id}]: {e}")
            message = f"建立失敗；診斷編號：{diagnostic_id}"
            if user_facing_failure:
                message = f"{user_facing_failure}\n診斷編號：{diagnostic_id}"
            return ServerCreationResult(
                "failed",
                message,
                diagnostic_id=diagnostic_id,
                cleanup_complete=cleanup_complete,
            )

    def _recover_orphans(self) -> None:
        """清除 crash 後的 staging 與未註冊 final instance"""
        root = self._root
        with self._lock:
            try:
                root_entries = list_bounded_directory(root, reject_reparse=False)
            except OSError:
                return
            for staging_path in root_entries:
                if not (staging_path.name.startswith(".msm-create-") and staging_path.name.endswith(".staging")):
                    continue
                if staging_path.is_dir():
                    self._cleanup_path(staging_path)
            for restore_staging in root_entries:
                if (
                    ".restore-" not in restore_staging.name
                    or ".restore-rollback-" in restore_staging.name
                    or not restore_staging.name.startswith(".")
                ):
                    continue
                if restore_staging.is_dir():
                    self._cleanup_path(restore_staging)
            for candidate in root_entries:
                if not candidate.is_dir() or not (candidate / self._MARKER_NAME).is_file():
                    continue
                config = self.server_crud.snapshot().get(candidate.name)
                registered_path = Path(config.path).resolve(strict=False) if config else None
                if registered_path == candidate.resolve(strict=False):
                    try:
                        delete_within(candidate, candidate / self._MARKER_NAME)
                    except OSError as e:
                        logger.warning(f"無法移除已註冊 instance 的 orphan marker: {e}")
                else:
                    self._cleanup_path(candidate)

    @staticmethod
    def _emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
        if callback is not None:
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"忽略 server creation progress callback 例外: {e}")

    def _check_disk_space(self, required_bytes: int = 500 * 1024 * 1024) -> None:
        try:
            if SystemUtils.get_free_disk_bytes(self._root) < required_bytes:
                raise OSError(f"可用磁碟空間不足，無法建立伺服器；至少需要 {required_bytes} bytes")
        except OSError:
            raise
        except Exception as e:
            logger.warning(f"檢查磁碟空間時發生例外: {e}")

    @staticmethod
    def _check_cancel(cancel_check: CancelCheck) -> None:
        if cancel_check():
            raise CreationCancelledError

    def _write_marker(self, directory: Path, plan: ServerCreationPlan, state: str) -> None:
        if not atomic_write_json(
            directory / self._MARKER_NAME,
            {"schema_version": 1, "transaction_id": plan.transaction_id, "state": state},
        ):
            raise OperationError("無法寫入 server creation transaction marker")

    @staticmethod
    def _validate_staged_instance(plan: ServerCreationPlan) -> None:
        required = [
            plan.staging_path / "eula.txt",
            plan.staging_path / "server.properties",
            plan.staging_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME,
        ]
        if plan.loader_type in {"vanilla", "fabric", "quilt"}:
            required.append(plan.staging_path / "server.jar")
        missing = [path.name for path in required if not path.is_file()]
        if plan.loader_type in {"forge", "neoforge"} and not (plan.staging_path / "libraries").is_dir():
            missing.append("libraries 資料夾")
        if missing:
            raise OperationError(f"伺服器建立內容不完整：{', '.join(missing)}")

    def _compensate(
        self,
        plan: ServerCreationPlan,
        moved_to_final: bool,
    ) -> bool:
        targets = [plan.final_path] if moved_to_final else [plan.staging_path]
        return all(self._cleanup_path(path) for path in targets)

    def _cleanup_path(self, path: Path) -> bool:
        if not path.exists():
            return True
        try:
            SystemUtils.kill_java_processes_in_path(path)
        except Exception as e:
            logger.warning(f"清理建立交易時無法終止 Java process: {e}")
        return delete_within(self._root, path)

    def _record_diagnostic(self, plan: ServerCreationPlan, phase: str, error: Any) -> str:
        diagnostic_id = f"server-create-{plan.transaction_id[:12]}"
        try:
            detail = str(error)
            for sensitive in (plan.name, str(plan.final_path), str(plan.staging_path), str(self._root)):
                if sensitive:
                    detail = detail.replace(sensitive, "<redacted>")
            issues_dir = resolve_stable_directory(self._root / ".issues", create=True)
            atomic_write_json(
                issues_dir / f"{diagnostic_id}.json",
                {
                    "schema_version": 1,
                    "diagnostic_id": diagnostic_id,
                    "operation": "server_creation",
                    "phase": phase,
                    "error_type": type(error).__name__,
                    "detail": detail,
                    "timestamp_epoch_ms": int(time.time() * 1000),
                },
            )
        except Exception as e:
            logger.error(f"無法寫入 server creation 診斷 [{diagnostic_id}]: {e}")
        return diagnostic_id


__all__ = ["CreateServerJourney"]
