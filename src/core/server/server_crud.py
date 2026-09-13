"""
伺服器管理器

負責建立、管理與設定 Minecraft 伺服器的核心邏輯
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from copy import copy as shallow_copy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, ClassVar

from src.models import ProgressEvent, ServerConfig, ServerOperationResult
from src.utils import (
    SAFE_TEXT_FILE_MAX_BYTES,
    HashUtils,
    OperationError,
    ServerCommands,
    atomic_write_json,
    atomic_write_text,
    delete_within,
    get_logger,
    get_shared_manager,
    is_path_within,
    is_reparse_point,
    list_bounded_directory,
    move_within,
    move_within_strict,
    open_regular_file,
    read_bytes_file,
    read_json,
    read_json_with_bytes,
    resolve_stable_directory,
    validate_server_name,
)

from .server_inspector import ServerInspector
from .server_runtime import ServerRuntime

logger = get_logger().bind(component="ServerManager")


def _clone_server_config(config: ServerConfig) -> ServerConfig:
    """複製設定的不可變欄位，僅複製唯一可變的 JVM 參數清單"""
    cloned = shallow_copy(config)
    cloned.jvm_args = list(config.jvm_args)
    return cloned


@dataclass(frozen=True, slots=True)
class ServerConfigRegistrySnapshot:
    """伺服器設定登錄表的不可變投影"""

    revision: str
    entries: tuple[tuple[str, ServerConfig], ...]

    def get(self, name: str) -> ServerConfig | None:
        """
        取得設定副本，避免 caller 修改 owner 內部狀態

        Args:
            name: 伺服器名稱

        Returns:
            找到的設定副本；不存在時回傳 None
        """
        for key, config in self.entries:
            if key == name:
                return _clone_server_config(config)
        return None

    def items(self) -> tuple[tuple[str, ServerConfig], ...]:
        """
        取得所有名稱與設定副本

        Returns:
            依登錄順序排列的名稱／設定元組
        """
        return tuple((name, _clone_server_config(config)) for name, config in self.entries)

    def values(self) -> tuple[ServerConfig, ...]:
        """
        取得所有設定副本

        Returns:
            依登錄順序排列的設定元組
        """
        return tuple(_clone_server_config(config) for _, config in self.entries)

    def __contains__(self, name: object) -> bool:
        return any(key == name for key, _ in self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)


@dataclass(frozen=True, slots=True)
class ServerConfigChangeSet:
    """一次登錄表提交所需的新增／取代與移除"""

    upserts: tuple[ServerConfig, ...] = ()
    removals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ServerConfigCommitResult:
    """登錄表批次提交結果"""

    success: bool
    snapshot: ServerConfigRegistrySnapshot
    error_kind: str = ""
    message: str = ""


@dataclass(slots=True)
class _RegistryState:
    configs: dict[str, ServerConfig]
    revision: str


class ServerCRUD:
    """伺服器檔案流程與伺服器設定登錄表的唯一 owner"""

    _shared_registry_states: ClassVar[dict[str, _RegistryState]] = {}
    _operation_locks_guard: ClassVar[threading.Lock] = threading.Lock()
    _operation_locks: ClassVar[dict[str, threading.RLock]] = {}
    _delete_cleanup_guard: ClassVar[threading.Lock] = threading.Lock()
    _active_delete_cleanups: ClassVar[set[str]] = set()

    _DELETE_PREFIX = ".msm-delete-"
    _DELETE_MARKER = ".msm-delete.json"
    _RESTORE_EXCLUDES: ClassVar[set[str]] = {"logs", "crash-reports", "backups", ".git"}

    STARTUP_CHECK_DELAY = 0.1

    def __init__(self, servers_root: str | None = None):
        if not servers_root:
            raise ValueError("ServerManager 必須指定 servers_root 路徑，且不可為空請於 UI 層先處理")
        self.servers_root = resolve_stable_directory(Path(servers_root), create=True)
        self.config_file = self.servers_root / "servers_config.json"
        config_existed = self.config_file.is_file()

        key = str(self.servers_root)
        with self._operation_locks_guard:
            self.operation_lock = self._operation_locks.setdefault(key, threading.RLock())
        self._registry_state = ServerCRUD._shared_registry_states.setdefault(
            key,
            _RegistryState(configs={}, revision=self._empty_revision()),
        )
        with self.operation_lock:
            registry_loaded = self._refresh_registry_locked()
            if not self.config_file.exists():
                self._persist_registry_locked(self._registry_state.configs)
            if registry_loaded and config_existed:
                self._recover_delete_tombstones_locked()
                self._recover_restore_transactions_locked()

    @staticmethod
    def _empty_revision() -> str:
        return HashUtils.digest_bytes(b"{}")

    @staticmethod
    def _revision_for_bytes(payload: bytes) -> str:
        return HashUtils.digest_bytes(payload)

    def _snapshot_locked(self) -> ServerConfigRegistrySnapshot:
        return ServerConfigRegistrySnapshot(
            revision=self._registry_state.revision,
            entries=tuple(
                (name, _clone_server_config(config)) for name, config in self._registry_state.configs.items()
            ),
        )

    def _serialize_registry(self, configs: Mapping[str, ServerConfig]) -> dict[str, dict[str, Any]]:
        data: dict[str, dict[str, Any]] = {}
        for name, config in configs.items():
            if not isinstance(config, ServerConfig):
                raise TypeError(f"無法序列化類型 {type(config).__name__} ({name})")
            data[name] = {
                "name": config.name,
                "minecraft_version": config.minecraft_version,
                "loader_type": config.loader_type,
                "loader_version": config.loader_version,
                "memory_max_mb": config.memory_max_mb,
                "memory_min_mb": config.memory_min_mb,
                "path": config.path,
                "backup_path": config.backup_path,
                "jvm_args": list(config.jvm_args),
            }
        return data

    def _persist_registry_locked(self, configs: Mapping[str, ServerConfig]) -> bool:
        try:
            data = self._serialize_registry(configs)
            if not atomic_write_json(self.config_file, data):
                logger.error("儲存伺服器設定失敗：無法寫入檔案")
                return False
            raw = read_bytes_file(self.config_file, max_bytes=SAFE_TEXT_FILE_MAX_BYTES)
            self._registry_state.revision = self._revision_for_bytes(raw) if raw is not None else self._empty_revision()
            logger.info("伺服器設定已原子提交到 servers_config.json")
            return True
        except Exception as e:
            logger.exception(f"儲存伺服器設定失敗: {e}")
            return False

    def _decode_registry(self, data: Any) -> dict[str, ServerConfig] | None:
        if not isinstance(data, dict):
            logger.warning("伺服器設定檔格式不是物件")
            return None
        valid_keys = {field.name for field in fields(ServerConfig)}
        decoded: dict[str, ServerConfig] = {}
        for name, config_data in data.items():
            if not isinstance(name, str) or not isinstance(config_data, dict):
                continue
            filtered_data = {key: value for key, value in config_data.items() if key in valid_keys}
            try:
                validated_name = validate_server_name(name)
                config = ServerConfig(**filtered_data)
                if config.name != validated_name:
                    raise ValueError("設定名稱與伺服器索引不一致")
                config.path = str(self._resolve_registered_server_path(validated_name, config.path))
            except (OSError, TypeError, ValueError) as e:
                logger.warning(f"略過不安全的伺服器設定 {name}: {e}")
                continue
            decoded[validated_name] = config
        return decoded

    def _refresh_registry_locked(self) -> bool:
        if not self.config_file.exists():
            self._registry_state.configs = {}
            self._registry_state.revision = self._empty_revision()
            return True
        result = read_json_with_bytes(self.config_file, max_bytes=SAFE_TEXT_FILE_MAX_BYTES)
        if result is None:
            logger.warning("伺服器設定檔為空、超過大小上限或無法讀取")
            return False
        data, raw = result
        decoded = self._decode_registry(data)
        if decoded is None:
            return False
        self._registry_state.configs = decoded
        self._registry_state.revision = self._revision_for_bytes(raw)
        return True

    def snapshot(self) -> ServerConfigRegistrySnapshot:
        """
        回傳目前完整登錄表投影與 revision

        Returns:
            不可變登錄表快照
        """
        with self.operation_lock:
            self._refresh_registry_locked()
            return self._snapshot_locked()

    def commit(
        self,
        change_set: ServerConfigChangeSet,
        expected_revision: str,
    ) -> ServerConfigCommitResult:
        """
        驗證並原子提交一次登錄表變更

        Args:
            change_set: 要新增／取代或移除的登錄變更
            expected_revision: 呼叫端讀取快照時的 revision

        Returns:
            提交結果與成功或失敗時的登錄表快照
        """
        with self.operation_lock:
            self._refresh_registry_locked()
            current = self._snapshot_locked()
            if expected_revision != current.revision:
                return ServerConfigCommitResult(
                    False,
                    current,
                    "conflict",
                    "伺服器設定已被其他程序修改，請重新載入後再試",
                )
            candidate = {name: _clone_server_config(config) for name, config in current.entries}
            try:
                removals = tuple(validate_server_name(name) for name in change_set.removals)
                for name in removals:
                    candidate.pop(name, None)
                for incoming in change_set.upserts:
                    config = _clone_server_config(incoming)
                    validated_name = validate_server_name(config.name)
                    config.path = str(self._resolve_registered_server_path(validated_name, config.path))
                    candidate[validated_name] = config
            except (OSError, TypeError, ValueError) as e:
                return ServerConfigCommitResult(False, current, "invalid", str(e))
            if not self._persist_registry_locked(candidate):
                return ServerConfigCommitResult(False, current, "write_failed", "無法原子寫入伺服器設定")
            self._registry_state.configs = candidate
            return ServerConfigCommitResult(True, self._snapshot_locked())

    def _resolve_server_path(self, raw_path: str | Path, *, require_exists: bool = False) -> Path:
        """解析並限制伺服器設定指定的路徑"""
        if not str(raw_path).strip():
            raise ValueError("伺服器路徑不可為空")
        candidate = Path(raw_path)
        if is_reparse_point(candidate):
            raise ValueError("伺服器路徑不可為符號連結或 reparse point")
        resolved = candidate.resolve(strict=require_exists)
        if resolved == self.servers_root or not is_path_within(self.servers_root, resolved, strict=False):
            raise ValueError(f"伺服器路徑必須位於伺服器根目錄內: {resolved}")
        return resolved

    def _resolve_registered_server_path(self, name: str, raw_path: str | Path) -> Path:
        """解析已註冊伺服器路徑並繫結名稱與 root 直接子目錄"""
        validated_name = validate_server_name(name)
        resolved = self._resolve_server_path(raw_path)
        if resolved.parent != self.servers_root or resolved.name.casefold() != validated_name.casefold():
            raise ValueError("伺服器路徑必須是與名稱一致的 root 直接子目錄")
        if resolved.exists() and (is_reparse_point(resolved) or not resolved.is_dir()):
            raise ValueError("已註冊伺服器路徑必須是一般資料夾")
        return resolved

    def prepare_server_files(self, config: ServerConfig) -> None:
        """
        在 transaction staging 目錄準備 EULA 與基礎資料夾

        Args:
            config: 指向 staging 目錄的伺服器設定
        """
        server_path = self._resolve_server_path(config.path)
        if not server_path.is_dir():
            raise FileNotFoundError("伺服器 staging 目錄不存在")
        if not self._create_eula_file(server_path):
            raise OperationError("建立 EULA 檔案失敗")
        self._create_server_structure(server_path, config.loader_type)

    def create_launch_script(
        self,
        config: ServerConfig,
        java_command_override: str | None = None,
        *,
        launch_target: str | None = None,
    ) -> bool:
        """
        建立伺服器啟動腳本

        Args:
            config: 伺服器設定與啟動參數來源
            java_command_override: 匯入既有伺服器時保留的原始 Java 啟動命令
            launch_target: 已由 ServerInspector 驗證的 JAR 或 args 啟動目標

        Returns:
            啟動腳本寫入成功時回傳 True，失敗時回傳 False
        """
        try:
            server_path = self._resolve_server_path(config.path)
        except (OSError, ValueError) as e:
            logger.error(f"拒絕建立啟動腳本，伺服器路徑無效: {e}")
            return False
        if java_command_override:
            java_command_str = ServerCommands.normalize_imported_java_command(java_command_override) or ""
            if not java_command_str:
                logger.error("拒絕寫入含不安全 cmd 語法的匯入啟動命令")
                return False
        else:
            resolved_target = launch_target
            if resolved_target and Path(resolved_target).suffix.lower() in {".bat", ".cmd", ".sh", ".ps1"}:
                resolved_target = None
            if not resolved_target and server_path.is_dir():
                detected = ServerInspector.find_main_jar(server_path, config.loader_type, config)
                if detected and detected.lower() != "@user_jvm_args.txt":
                    resolved_target = detected
            command_result = ServerCommands.build_java_command(
                config,
                return_list=False,
                launch_target=resolved_target,
            )
            java_command_str = str(command_result).strip()
            if not java_command_str:
                logger.error("拒絕建立含不安全啟動參數的批次腳本")
                return False
        bat_lines = [
            "@echo off",
            "chcp 65001 >nul",
            'cd /d "%~dp0"',
            "",
            java_command_str,
        ]
        bat_content = "\n".join(bat_lines)
        start_script_path = server_path / "start_server.bat"
        try:
            if start_script_path.exists():
                existing_bytes = read_bytes_file(start_script_path, max_bytes=SAFE_TEXT_FILE_MAX_BYTES)
                if existing_bytes is None:
                    existing_bytes = b""
                existing_has_bom = existing_bytes.startswith(b"\xef\xbb\xbf")
                existing_content = existing_bytes.decode("utf-8-sig", errors="ignore")
                if existing_content == bat_content and not existing_has_bom:
                    return True
        except Exception as e:
            logger.warning(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")
        return atomic_write_text(start_script_path, bat_content, encoding="utf-8", errors="replace")

    def _recover_delete_tombstones_locked(self) -> None:
        """
        恢復或清理上次非正常結束留下的刪除 tombstone

        已登錄且原路徑消失時採 fail-safe 還原
        已不在登錄中的 tombstone 視為已提交刪除並交由背景清理
        """
        try:
            entries = list_bounded_directory(self.servers_root, reject_reparse=False)
        except OSError as e:
            logger.warning(f"無法掃描刪除交易暫存目錄: {e}")
            return

        for candidate in entries:
            if not candidate.name.startswith(self._DELETE_PREFIX):
                continue
            try:
                if is_reparse_point(candidate) or not candidate.is_dir():
                    continue
            except OSError:
                continue

            marker = candidate / self._DELETE_MARKER
            payload = read_json(marker, {}, allowed_root=candidate)
            journal_path = self.servers_root / f"{candidate.name}.json"
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                payload = read_json(journal_path, {}, allowed_root=self.servers_root)
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                logger.warning(f"保留無法驗證的刪除 tombstone，避免誤刪資料: {candidate}")
                continue
            try:
                server_name = validate_server_name(str(payload.get("server_name", "")))
            except ValueError as e:
                logger.warning(f"保留名稱無效的刪除 tombstone {candidate.name}: {e}")
                continue

            config = self._registry_state.configs.get(server_name)
            if config is None:
                self._schedule_delete_cleanup(candidate)
                delete_within(self.servers_root, journal_path)
                continue

            try:
                original_path = self._resolve_registered_server_path(server_name, config.path)
            except (OSError, ValueError) as e:
                logger.warning(f"無法安全恢復刪除 tombstone {candidate.name}: {e}")
                continue
            if original_path.exists():
                logger.warning(f"刪除 tombstone 與已登錄伺服器同時存在，為避免資料遺失而保留暫存目錄: {candidate.name}")
                continue
            try:
                move_within_strict(self.servers_root, candidate, original_path)
                if not delete_within(original_path, original_path / self._DELETE_MARKER):
                    logger.warning(f"已恢復伺服器但無法移除刪除交易標記: {server_name}")
                delete_within(self.servers_root, journal_path)
                logger.warning(f"偵測到未提交完成的刪除交易，已恢復伺服器目錄: {server_name}")
            except OSError as e:
                logger.exception(f"恢復刪除 tombstone 失敗 {candidate.name}: {e}")

    def _recover_restore_transactions_locked(self) -> None:
        """恢復中斷的還原目錄交換，優先還原原始伺服器資料"""
        for server_name, config in self._registry_state.configs.items():
            try:
                server_path = self._resolve_registered_server_path(server_name, config.path)
                parent = resolve_stable_directory(server_path.parent)
                candidates = list_bounded_directory(parent, reject_reparse=False)
            except (OSError, ValueError) as e:
                logger.warning(f"無法掃描還原交易暫存目錄 {server_name}: {e}")
                continue
            prefix = f".{server_path.name}.restore-rollback-"
            for journal_path in candidates:
                if not journal_path.name.startswith(prefix) or journal_path.suffix != ".json":
                    continue
                payload = read_json(journal_path, {}, allowed_root=parent)
                if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                    continue
                rollback_path = parent / journal_path.name.removesuffix(".json")
                prepared_path = Path(str(payload.get("prepared_path", "")))
                if not rollback_path.is_dir() or is_reparse_point(rollback_path):
                    if server_path.exists():
                        delete_within(parent, journal_path)
                    continue
                try:
                    if server_path.exists():
                        delete_within(parent, rollback_path)
                        delete_within(parent, journal_path)
                        continue
                    if prepared_path.is_dir() and is_path_within(parent, prepared_path, strict=False):
                        for excluded_name in self._RESTORE_EXCLUDES:
                            preserved_path = prepared_path / excluded_name
                            if preserved_path.exists() and not move_within(
                                parent, preserved_path, rollback_path / excluded_name
                            ):
                                raise OSError(f"無法恢復排除目錄: {excluded_name}")
                    if not move_within(parent, rollback_path, server_path):
                        raise OSError("無法恢復中斷還原前的伺服器目錄")
                    delete_within(parent, journal_path)
                    logger.warning(f"已恢復中斷的伺服器還原交易: {server_name}")
                except OSError as e:
                    logger.exception(f"恢復中斷還原交易失敗 {server_name}: {e}")

    def delete_server_result(
        self,
        server_name: str,
        *,
        server_runtime: ServerRuntime,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> ServerOperationResult:
        """
        刪除伺服器

        Args:
            server_name: 要刪除的伺服器名稱

        Returns:
            刪除流程結果
        """
        tombstone_path: Path | None = None
        delete_journal_path: Path | None = None
        server_path: Path | None = None
        maintenance_acquired = False
        begin_maintenance = getattr(server_runtime, "begin_maintenance", None)
        if callable(begin_maintenance):
            maintenance_acquired = bool(begin_maintenance(server_name))
            if not maintenance_acquired:
                return ServerOperationResult(
                    success=False,
                    title="無法刪除",
                    message=f"伺服器 {server_name} 正在執行或進行其他維護操作",
                    server_name=server_name,
                )
        try:
            with self.operation_lock:
                baseline = self.snapshot()
                config = baseline.get(server_name)
                if config is None:
                    return ServerOperationResult(
                        success=False,
                        title="刪除失敗",
                        message=f"找不到伺服器: {server_name}",
                        server_name=server_name,
                    )
                if server_runtime.observe(server_name).is_running:
                    return ServerOperationResult(
                        success=False,
                        title="無法刪除",
                        message=f"伺服器 {server_name} 正在執行中，請先停止伺服器",
                        server_name=server_name,
                    )

                try:
                    server_path = self._resolve_registered_server_path(server_name, config.path)
                except (OSError, ValueError) as e:
                    logger.error(f"拒絕刪除伺服器，路徑無效: {e}")
                    return ServerOperationResult(
                        success=False,
                        title="刪除失敗",
                        message=f"拒絕刪除不安全的伺服器路徑: {e}",
                        server_name=server_name,
                    )

                if not server_runtime.prepare_maintenance(server_name, server_path):
                    return ServerOperationResult(
                        success=False,
                        title="無法刪除",
                        message=f"伺服器 {server_name} 的背景行程尚未完全結束",
                        server_name=server_name,
                    )

                if server_path.exists():
                    tombstone_path = self.servers_root / f"{self._DELETE_PREFIX}{uuid.uuid4().hex}"
                    delete_journal_path = self.servers_root / f"{tombstone_path.name}.json"
                    if not atomic_write_json(
                        delete_journal_path,
                        {
                            "schema_version": 1,
                            "server_name": server_name,
                            "created_epoch_ms": int(time.time() * 1000),
                        },
                    ):
                        raise OSError("無法建立刪除交易識別標記")
                    self._emit_progress(progress_callback, "delete_move", "正在準備安全刪除...")
                    last_error: OSError | None = None
                    for delay in (0.0, 0.1, 0.25, 0.5, 0.75):
                        if delay:
                            time.sleep(delay)
                        self._resolve_registered_server_path(server_name, config.path)
                        try:
                            move_within_strict(self.servers_root, server_path, tombstone_path)
                            last_error = None
                            break
                        except OSError as e:
                            last_error = e
                            if getattr(e, "winerror", None) not in {5, 32, 33}:
                                break
                    if last_error is not None:
                        raise OSError(
                            getattr(last_error, "winerror", None) or 0,
                            f"無法將伺服器目錄移至刪除暫存位置：{last_error}",
                        ) from last_error
                    if not move_within(self.servers_root, delete_journal_path, tombstone_path / self._DELETE_MARKER):
                        move_within_strict(self.servers_root, tombstone_path, server_path)
                        raise OSError("無法移入刪除交易識別標記")
                    delete_journal_path = None

                commit_result = self.commit(
                    ServerConfigChangeSet(removals=(server_name,)),
                    expected_revision=baseline.revision,
                )
                if not commit_result.success:
                    if tombstone_path is not None:
                        if not move_within(self.servers_root, tombstone_path, server_path):
                            raise OSError("無法復原刪除暫存目錄")
                        if not delete_within(server_path, server_path / self._DELETE_MARKER):
                            logger.warning(f"已復原伺服器但無法移除刪除交易標記: {server_name}")
                        tombstone_path = None
                    return ServerOperationResult(
                        success=False,
                        title="刪除失敗",
                        message=f"無法儲存刪除後的伺服器設定: {commit_result.message or server_name}",
                        server_name=server_name,
                    )
                self._emit_progress(progress_callback, "delete_committed", "伺服器已從列表移除")
                if tombstone_path is not None:
                    cleanup_path = tombstone_path
                    tombstone_path = None
                    self._schedule_delete_cleanup(cleanup_path)
                return ServerOperationResult(
                    success=True,
                    message=f"伺服器 {server_name} 已刪除",
                    server_name=server_name,
                )
        except Exception as e:
            error_message = str(e)
            if (
                tombstone_path is not None
                and server_path is not None
                and tombstone_path.exists()
                and not server_path.exists()
            ):
                try:
                    if not move_within(self.servers_root, tombstone_path, server_path):
                        raise OSError("無法復原刪除暫存目錄")
                    if not delete_within(server_path, server_path / self._DELETE_MARKER):
                        logger.warning(f"已復原伺服器但無法移除刪除交易標記: {server_name}")
                except OSError as e:
                    logger.exception(f"刪除失敗後無法復原伺服器目錄: {e}")
            if delete_journal_path is not None:
                delete_within(self.servers_root, delete_journal_path)
            logger.exception(f"刪除伺服器失敗: {error_message}")
            return ServerOperationResult(
                success=False,
                title="刪除失敗",
                message=f"無法刪除伺服器 {server_name} 錯誤: {error_message}",
                server_name=server_name,
            )
        finally:
            if maintenance_acquired:
                end_maintenance = getattr(server_runtime, "end_maintenance", None)
                if callable(end_maintenance):
                    end_maintenance(server_name)

    @staticmethod
    def _emit_progress(callback: Callable[[ProgressEvent], None] | None, phase: str, message: str) -> None:
        if callback is None:
            return
        try:
            callback(ProgressEvent(phase, message))
        except Exception as e:
            logger.debug(f"忽略刪除進度回呼例外: {e}")

    def _schedule_delete_cleanup(self, tombstone_path: Path) -> bool:
        """
        將已提交刪除的 tombstone 交由 daemon thread 清理

        伺服器登錄與原路徑已在同步交易中完成移除
        大型世界目錄的遞迴 unlink 不再阻塞 UI 完成通知與其他伺服器操作
        """

        cleanup_key = os.path.normcase(str(tombstone_path.resolve(strict=False)))
        with self._delete_cleanup_guard:
            if cleanup_key in self._active_delete_cleanups:
                return True
            self._active_delete_cleanups.add(cleanup_key)

        def _cleanup() -> None:
            try:
                for delay in (0.0, 0.25, 1.0, 2.0, 5.0):
                    if delay:
                        time.sleep(delay)
                    if delete_within(self.servers_root, tombstone_path):
                        return
                logger.warning(f"伺服器已移除，但暫存刪除目錄仍無法清理: {tombstone_path}")
            finally:
                with self._delete_cleanup_guard:
                    self._active_delete_cleanups.discard(cleanup_key)

        try:
            get_shared_manager().run(_cleanup)
            return True
        except RuntimeError as e:
            with self._delete_cleanup_guard:
                self._active_delete_cleanups.discard(cleanup_key)
            logger.warning(f"無法啟動背景刪除工作，將於後續啟動清理 tombstone: {e}")
            return False

    def get_server_log_file(self, server_name: str) -> Path | None:
        """
        取得伺服器日誌檔案路徑

        Args:
            server_name: 目標伺服器名稱

        Returns:
            找到的日誌檔案路徑；找不到時回傳 None
        """
        try:
            server_config = self.snapshot().get(server_name)
            if server_config is None:
                return None
            server_path = self._resolve_server_path(server_config.path)
            log_files = [
                server_path / "logs" / "latest.log",
                server_path / "server.log",
                server_path / "logs" / "server.log",
            ]
            for log_file in log_files:
                if is_reparse_point(log_file.parent):
                    continue
                try:
                    with open_regular_file(log_file, allowed_root=server_path):
                        return log_file
                except OSError:
                    continue
            return None
        except Exception as e:
            logger.exception(f"取得伺服器日誌檔案失敗: {e}")
            return None

    def _create_eula_file(self, server_path: Path) -> bool:
        """建立並同意 EULA 檔案"""
        eula_content = "eula=true"
        return atomic_write_text(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """建立伺服器檔案結構"""
        if loader_type.lower() == "vanilla":
            directories = ["world", "logs"]
        elif loader_type.lower() in ["forge", "fabric", "quilt", "neoforge"]:
            directories = ["world", "plugins", "mods", "config", "logs"]
        else:
            directories = ["world", "logs"]
            logger.warning(f"未知 loader_type: {loader_type}，使用預設目錄結構")
        for directory in directories:
            resolve_stable_directory(path / directory, create=True)


__all__ = ["ServerCRUD", "ServerConfigChangeSet"]
