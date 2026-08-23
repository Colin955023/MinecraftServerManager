"""以 staging、單一 commit point 與統一補償建立伺服器實例"""

from __future__ import annotations

import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.core import LoaderManager, ServerCRUD
from src.models import (
    ServerConfig,
    ServerCreationPlan,
    ServerCreationResult,
    ServerCreationWarning,
)
from src.utils import (
    CreationCancelledError,
    PathUtils,
    ServerCommands,
    SystemUtils,
    atomic_write_json,
    get_logger,
)

logger = get_logger().bind(component="ServerCreation")

ProgressCallback = Callable[[int, str], None]
CancelCheck = Callable[[], bool]
_CreationCancelled = CreationCancelledError


class ServerCreationService:
    """伺服器建立 journey 的唯一 owner"""

    _MARKER_NAME = ".msm-server-creation.json"
    _STAGING_GLOB = ".msm-create-*.staging"

    def __init__(self, server_crud: ServerCRUD, loader_manager: LoaderManager) -> None:
        self.server_crud = server_crud
        self.loader_manager = loader_manager
        self._root = server_crud.servers_root.resolve()
        self._lock = server_crud.operation_lock
        self.recover_orphans()

    def plan(
        self,
        config: ServerConfig,
        *,
        properties: dict[str, str] | None = None,
        user_java_path: str | None = None,
    ) -> ServerCreationPlan:
        """
        驗證輸入並建立不會寫入磁碟的交易計畫

        Args:
            config: 使用者選定的伺服器設定
            properties: 選用的 server.properties；省略時使用預設值
            user_java_path: 選用的 Java 執行檔路徑

        Returns:
            包含 staging、artifact 與警告資訊的不可變計畫
        """
        name = str(config.name or "")
        if not name or name != name.strip():
            raise ValueError("伺服器名稱不可為空白或包含前後空白")
        root = self._root
        final_path = (root / name).resolve(strict=False)
        if final_path.parent != root or not PathUtils.is_path_within(root, final_path, strict=False):
            raise ValueError("無效的伺服器名稱（路徑遍歷偵測）")
        if name in self.server_crud.servers or final_path.exists():
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
        if int(config.memory_max_mb) <= 0:
            raise ValueError("最大記憶體必須大於 0")
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
        warnings: list[ServerCreationWarning] = []
        if artifact is not None and not artifact.expected_hash:
            warnings.append(
                ServerCreationWarning(
                    "installer_checksum_missing",
                    f"{loader_type} installer 找不到可用的 SHA-1 / SHA-256 / SHA-512 驗證資訊",
                )
            )
        transaction_id = uuid.uuid4().hex
        resolved_properties = self.server_crud.get_default_server_properties() if properties is None else properties
        return ServerCreationPlan(
            transaction_id=transaction_id,
            name=name,
            minecraft_version=minecraft_version,
            loader_type=loader_type,
            loader_version=loader_version,
            memory_max_mb=int(config.memory_max_mb),
            memory_min_mb=int(config.memory_min_mb) if config.memory_min_mb is not None else None,
            jvm_args=tuple(str(arg) for arg in config.jvm_args),
            properties=tuple(sorted((str(key), str(value)) for key, value in resolved_properties.items())),
            final_path=final_path,
            staging_path=root / f".msm-create-{transaction_id}.staging",
            user_java_path=normalized_java_path,
            installer_artifact=artifact,
            warnings=tuple(warnings),
        )

    def execute(
        self,
        plan: ServerCreationPlan,
        *,
        allow_unverified_installer: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ServerCreationResult:
        """
        執行建立計畫並在失敗時補償已寫入資源

        Args:
            plan: 已完成驗證的建立計畫
            allow_unverified_installer: 是否接受缺少 checksum 的安裝器
            progress_callback: 接收進度百分比與文字的回呼
            cancel_check: 回傳是否要求取消的檢查函式

        Returns:
            明確區分完成、取消、失敗與需確認的結果
        """
        if plan.requires_unverified_installer_confirmation and not allow_unverified_installer:
            return ServerCreationResult("confirmation_required", "Loader installer 缺少 checksum，尚未取得允許")
        cancel_check = cancel_check or (lambda: False)
        with self._lock:
            return self._execute_locked(plan, progress_callback, cancel_check)

    def _execute_locked(
        self,
        plan: ServerCreationPlan,
        progress_callback: ProgressCallback | None,
        cancel_check: CancelCheck,
    ) -> ServerCreationResult:
        phase = "validate"
        config = plan.build_config(plan.staging_path)
        moved_to_final = False
        registered = False
        previous_config = self.server_crud.servers.get(plan.name)
        try:
            phase = "validate"
            self._check_disk_space()
            self._check_cancel(cancel_check)
            if self.server_crud.servers_root.resolve() != self._root:
                raise RuntimeError("伺服器根目錄已變更，建立計畫已失效")
            if plan.final_path.parent != self._root or plan.staging_path.parent != self._root:
                raise ValueError("建立計畫路徑不屬於目前伺服器根目錄")
            if plan.final_path.exists() or plan.name in self.server_crud.servers:
                raise FileExistsError("同名伺服器已存在，建立計畫已失效")
            if plan.staging_path.exists():
                raise FileExistsError("交易 staging 路徑已存在")

            phase = "stage"
            self._emit(progress_callback, 5, "正在準備交易暫存目錄...")
            plan.staging_path.mkdir()
            self._write_marker(plan.staging_path, plan, "staging")
            self.server_crud.prepare_server_files(config, dict(plan.properties))
            self._check_cancel(cancel_check)

            phase = "artifact"
            current_progress = 15
            self._emit(progress_callback, current_progress, "正在下載並驗證伺服器檔案...")

            def loader_progress(*args: Any) -> None:
                nonlocal current_progress
                if len(args) == 1:
                    msg = str(args[0])
                    if "執行" in msg or "安裝" in msg:
                        current_progress = max(current_progress, 75)
                    self._emit(progress_callback, current_progress, msg)
                elif len(args) == 2 and isinstance(args[0], (int, float)) and isinstance(args[1], (int, float)):
                    total = float(args[1])
                    percent = 15 if total <= 0 else int(15 + min(1.0, float(args[0]) / total) * 58)
                    current_progress = max(current_progress, percent)
                    self._emit(progress_callback, current_progress, "正在下載伺服器檔案...")

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
                raise RuntimeError("下載、checksum 驗證或 Loader installer 執行失敗")

            phase = "launch_script"
            current_progress = max(current_progress, 82)
            self._emit(progress_callback, current_progress, "正在建立啟動腳本...")
            if not self.server_crud.create_launch_script(config):
                raise RuntimeError("建立啟動腳本失敗")
            self._validate_staged_instance(plan)
            self._check_cancel(cancel_check)
            self._write_marker(plan.staging_path, plan, "prepared")

            phase = "commit"
            current_progress = max(current_progress, 92)
            self._emit(progress_callback, current_progress, "正在提交伺服器實例...")
            plan.staging_path.replace(plan.final_path)
            moved_to_final = True
            config.path = str(plan.final_path)
            self._write_marker(plan.final_path, plan, "moved")
            self.server_crud.servers[plan.name] = config
            registered = True
            if not self.server_crud.write_servers_config():
                raise RuntimeError("儲存 servers_config.json 失敗")
            marker = plan.final_path / self._MARKER_NAME
            try:
                marker.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"已提交實例但無法移除 transaction marker: {exc}")
            self._emit(progress_callback, 100, "伺服器建立完成！")
            return ServerCreationResult("completed", f"伺服器 {plan.name} 已建立", config=config)
        except _CreationCancelled:
            cleanup_complete = self._compensate(plan, moved_to_final, registered, previous_config)
            diagnostic_id = self._record_diagnostic(plan, phase, "cancelled")
            return ServerCreationResult(
                "cancelled",
                "使用者已取消建立伺服器",
                diagnostic_id=diagnostic_id,
                cleanup_complete=cleanup_complete,
            )
        except Exception as exc:
            cleanup_complete = self._compensate(plan, moved_to_final, registered, previous_config)
            diagnostic_id = self._record_diagnostic(plan, phase, exc)
            logger.exception(f"伺服器建立交易失敗 [{diagnostic_id}]: {exc}")
            return ServerCreationResult(
                "failed",
                f"建立失敗；診斷編號：{diagnostic_id}",
                diagnostic_id=diagnostic_id,
                cleanup_complete=cleanup_complete,
            )

    def recover_orphans(self) -> None:
        """清除 crash 後的 staging 與未註冊 final instance"""
        root = self._root
        with self._lock:
            for staging_path in root.glob(self._STAGING_GLOB):
                if staging_path.is_dir():
                    self._cleanup_path(staging_path)
            for candidate in root.iterdir():
                if not candidate.is_dir() or not (candidate / self._MARKER_NAME).is_file():
                    continue
                config = self.server_crud.servers.get(candidate.name)
                registered_path = Path(config.path).resolve(strict=False) if config else None
                if registered_path == candidate.resolve(strict=False):
                    try:
                        (candidate / self._MARKER_NAME).unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning(f"無法移除已註冊 instance 的 orphan marker: {exc}")
                else:
                    self._cleanup_path(candidate)

    @staticmethod
    def _emit(callback: ProgressCallback | None, percent: int, message: str) -> None:
        if callback is not None:
            try:
                callback(percent, message)
            except Exception as exc:
                logger.warning(f"忽略 server creation progress callback 例外: {exc}")

    def _check_disk_space(self, required_bytes: int = 500 * 1024 * 1024) -> None:
        try:
            if shutil.disk_usage(self._root).free < required_bytes:
                raise OSError(f"可用磁碟空間不足，無法建立伺服器；至少需要 {required_bytes} bytes")
        except OSError:
            raise
        except Exception as exc:
            logger.warning(f"檢查磁碟空間時發生異常: {exc}")

    @staticmethod
    def _check_cancel(cancel_check: CancelCheck) -> None:
        if cancel_check():
            raise _CreationCancelled

    def _write_marker(self, directory: Path, plan: ServerCreationPlan, state: str) -> None:
        if not atomic_write_json(
            directory / self._MARKER_NAME,
            {"schema_version": 1, "transaction_id": plan.transaction_id, "state": state},
        ):
            raise RuntimeError("無法寫入 server creation transaction marker")

    @staticmethod
    def _validate_staged_instance(plan: ServerCreationPlan) -> None:
        required = [
            plan.staging_path / "eula.txt",
            plan.staging_path / "server.properties",
            plan.staging_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME,
        ]
        if plan.loader_type in {"vanilla", "fabric", "quilt"}:
            required.append(plan.staging_path / "server.jar")
        if plan.loader_type in {"forge", "neoforge"}:
            required.append(plan.staging_path / "run.bat")
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"伺服器建立內容不完整：{', '.join(missing)}")

    def _compensate(
        self,
        plan: ServerCreationPlan,
        moved_to_final: bool,
        registered: bool,
        previous_config: ServerConfig | None,
    ) -> bool:
        if registered:
            if previous_config is None:
                self.server_crud.servers.pop(plan.name, None)
            else:
                self.server_crud.servers[plan.name] = previous_config
            self.server_crud.write_servers_config()
        targets = [plan.final_path] if moved_to_final else [plan.staging_path]
        return all(self._cleanup_path(path) for path in targets)

    def _cleanup_path(self, path: Path) -> bool:
        if not path.exists():
            return True
        try:
            SystemUtils.kill_java_processes_in_path(path)
        except Exception as exc:
            logger.warning(f"清理建立交易時無法終止 Java process: {exc}")
        return PathUtils.delete_within(self._root, path)

    def _record_diagnostic(self, plan: ServerCreationPlan, phase: str, error: Any) -> str:
        diagnostic_id = f"server-create-{plan.transaction_id[:12]}"
        try:
            detail = str(error)
            for sensitive in (plan.name, str(plan.final_path), str(plan.staging_path), str(self._root)):
                if sensitive:
                    detail = detail.replace(sensitive, "<redacted>")
            issues_dir = self._root / ".issues"
            issues_dir.mkdir(exist_ok=True)
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
        except Exception as exc:
            logger.error(f"無法寫入 server creation 診斷 [{diagnostic_id}]: {exc}")
        return diagnostic_id


class CreateServerJourney:
    """建立伺服器實例的 deep module 入口"""

    def __init__(self, server_crud: ServerCRUD, loader_manager: LoaderManager) -> None:
        self._service = ServerCreationService(server_crud, loader_manager)

    def plan(
        self,
        config: ServerConfig,
        *,
        user_java_path: str | None = None,
    ) -> ServerCreationPlan:
        """
        產生不可變建立計畫

        Args:
            config: 使用者選定的伺服器設定
            user_java_path: 選用的 Java 執行檔路徑

        Returns:
            不可變的建立計畫
        """
        return self._service.plan(config, user_java_path=user_java_path)

    def execute(
        self,
        plan: ServerCreationPlan,
        *,
        allow_unverified_installer: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ServerCreationResult:
        """
        執行計畫至單一 commit point；失敗時補償

        Args:
            plan: 已完成驗證的建立計畫
            allow_unverified_installer: 是否接受缺少 checksum 的安裝器
            progress_callback: 接收進度百分比與文字的回呼
            cancel_check: 回傳是否要求取消的檢查函式

        Returns:
            建立結果
        """
        return self._service.execute(
            plan,
            allow_unverified_installer=allow_unverified_installer,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )


__all__ = ["CreateServerJourney", "ServerCreationService"]
