"""server.properties 的唯一真相來源與原子提交邊界"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.utils import (
    SAFE_TEXT_FILE_MAX_BYTES,
    atomic_write_text,
    get_logger,
    is_path_within,
    read_bytes_file,
)

from .server_properties_codec import PropertiesDocumentCodec, PropertiesSchema

logger = get_logger().bind(component="ServerPropertiesStore")

ServerPropertiesReadStatus = Literal["ok", "missing", "empty", "invalid", "unreadable"]
ServerPropertiesUpdateError = Literal[
    "", "missing_server", "unsafe_path", "read_failed", "conflict", "invalid", "write_failed"
]


@dataclass(frozen=True, slots=True)
class ServerPropertiesSnapshot:
    """server.properties 的不可變內容與內容 revision"""

    server_name: str
    status: ServerPropertiesReadStatus
    revision: str
    entries: tuple[tuple[str, str], ...] = ()
    message: str = ""
    property_categories: tuple[tuple[str, tuple[str, ...]], ...] = ()
    property_descriptions: tuple[tuple[str, str], ...] = ()
    default_properties: tuple[tuple[str, str], ...] = ()
    boolean_properties: tuple[str, ...] = ()

    @property
    def properties(self) -> dict[str, str]:
        return dict(self.entries)

    @property
    def readable(self) -> bool:
        return self.status in {"ok", "empty", "missing"}

    @property
    def categories(self) -> dict[str, list[str]]:
        return {name: list(properties) for name, properties in self.property_categories}

    @property
    def descriptions(self) -> dict[str, str]:
        return dict(self.property_descriptions)

    @property
    def defaults(self) -> dict[str, str]:
        return dict(self.default_properties)


@dataclass(frozen=True, slots=True)
class ServerPropertiesUpdateResult:
    """屬性 patch 提交結果"""

    success: bool
    snapshot: ServerPropertiesSnapshot
    error_kind: ServerPropertiesUpdateError = ""
    message: str = ""


class ServerPropertiesStore:
    """集中路徑安全、解析、schema、revision conflict 與原子寫入"""

    _MISSING_REVISION = "missing"

    def __init__(self, server_crud: Any) -> None:
        self.server_crud = server_crud
        self._root = Path(server_crud.servers_root).resolve()
        self._lock = server_crud.operation_lock

    def describe(self, server_name: str) -> ServerPropertiesSnapshot:
        """
        讀取已登錄伺服器，並區分各種讀取狀態

        Args:
            server_name: 已登錄的伺服器名稱

        Returns:
            不可變屬性內容、revision 與明確讀取狀態
        """
        try:
            path = self._registered_properties_path(server_name)
        except KeyError:
            return self._metadata_snapshot(server_name, "invalid", "", message="找不到伺服器設定")
        except ValueError as e:
            return self._metadata_snapshot(server_name, "invalid", "", message=str(e))
        with self._lock:
            return self._read_path(server_name, path)

    def commit(
        self,
        server_name: str,
        patch: Mapping[str, str],
        *,
        expected_revision: str,
    ) -> ServerPropertiesUpdateResult:
        """
        以 expected revision 提交真正變動的鍵

        Args:
            server_name: 已登錄的伺服器名稱
            patch: 相對於載入 baseline 的變更鍵值
            expected_revision: 對話框載入時取得的內容 revision

        Returns:
            成功時含新快照；失敗時含衝突、驗證或寫入錯誤
        """
        try:
            path = self._registered_properties_path(server_name)
        except KeyError:
            snapshot = self._metadata_snapshot(server_name, "invalid", "", message="找不到伺服器設定")
            return ServerPropertiesUpdateResult(False, snapshot, "missing_server", snapshot.message)
        except ValueError as e:
            snapshot = self._metadata_snapshot(server_name, "invalid", "", message=str(e))
            return ServerPropertiesUpdateResult(False, snapshot, "unsafe_path", str(e))
        with self._lock:
            current = self._read_path(server_name, path)
            if not current.readable:
                return ServerPropertiesUpdateResult(False, current, "read_failed", current.message)
            if current.revision != expected_revision:
                return ServerPropertiesUpdateResult(
                    False,
                    current,
                    "conflict",
                    "server.properties 已被其他程序修改，請重新載入後再儲存",
                )
            normalized_patch = {str(key): "" if value is None else str(value) for key, value in patch.items()}
            merged = current.properties
            merged.update(normalized_patch)
            valid, errors = PropertiesSchema.validate_properties(merged)
            if not valid:
                return ServerPropertiesUpdateResult(False, current, "invalid", "\n".join(errors))
            if not normalized_patch:
                return ServerPropertiesUpdateResult(True, current)
            payload = PropertiesDocumentCodec.serialize(merged)
            if not atomic_write_text(path, payload, encoding="utf-8"):
                return ServerPropertiesUpdateResult(False, current, "write_failed", "原子寫入 server.properties 失敗")
            updated = self._snapshot(server_name, "ok", payload, merged)
            logger.info(f"已原子提交 server.properties: server={server_name}, changed_keys={sorted(normalized_patch)}")
            return ServerPropertiesUpdateResult(True, updated)

    def initialize(self, server_path: Path, overrides: Mapping[str, str]) -> ServerPropertiesSnapshot:
        """
        在建立交易 staging 目錄寫入完整初始屬性

        Args:
            server_path: 位於受管根目錄內的 staging 路徑
            overrides: 建立計畫要覆寫的屬性

        Returns:
            已提交內容的不可變快照
        """
        resolved = Path(server_path).resolve(strict=False)
        if not is_path_within(self._root, resolved, strict=False):
            raise ValueError("伺服器 staging 路徑不在伺服器根目錄內")
        if not resolved.is_dir():
            raise FileNotFoundError("伺服器 staging 目錄不存在")
        normalized = PropertiesSchema.default_values()
        normalized.update({str(key): "" if value is None else str(value) for key, value in overrides.items()})
        valid, errors = PropertiesSchema.validate_properties(normalized)
        if not valid:
            raise ValueError("\n".join(errors))
        payload = PropertiesDocumentCodec.serialize(normalized)
        path = resolved / "server.properties"
        with self._lock:
            if not atomic_write_text(path, payload, encoding="utf-8"):
                raise OSError("原子寫入 server.properties 失敗")
        return self._snapshot(resolved.name, "ok", payload, normalized)

    def _registered_properties_path(self, server_name: str) -> Path:
        config = self.server_crud.snapshot().get(server_name)
        if config is None:
            raise KeyError(server_name)
        server_path = Path(config.path).resolve(strict=False)
        if not is_path_within(self._root, server_path, strict=False):
            raise ValueError(f"伺服器路徑必須位於伺服器資料夾內: {server_path}")
        return server_path / "server.properties"

    @staticmethod
    def _metadata_snapshot(
        server_name: str,
        status: ServerPropertiesReadStatus,
        revision: str,
        *,
        entries: tuple[tuple[str, str], ...] = (),
        message: str = "",
    ) -> ServerPropertiesSnapshot:
        return ServerPropertiesSnapshot(
            server_name=server_name,
            status=status,
            revision=revision,
            entries=entries,
            message=message,
            property_categories=tuple(
                (name, tuple(properties))
                for name, properties in PropertiesDocumentCodec.get_property_categories().items()
            ),
            property_descriptions=tuple(PropertiesDocumentCodec.get_property_descriptions().items()),
            default_properties=tuple(PropertiesSchema.default_values().items()),
            boolean_properties=tuple(
                name for name, rule in PropertiesSchema.VALIDATION_RULES.items() if rule[0] == "bool"
            ),
        )

    @classmethod
    def _read_path(cls, server_name: str, path: Path) -> ServerPropertiesSnapshot:
        if not path.exists():
            return cls._metadata_snapshot(server_name, "missing", cls._MISSING_REVISION)
        try:
            raw = read_bytes_file(path, max_bytes=SAFE_TEXT_FILE_MAX_BYTES)
            if raw is None:
                return cls._metadata_snapshot(
                    server_name,
                    "unreadable",
                    "",
                    message=f"server.properties 超過安全大小上限 {SAFE_TEXT_FILE_MAX_BYTES} bytes 或不是一般檔案",
                )
        except PermissionError as e:
            return cls._metadata_snapshot(server_name, "unreadable", "", message=str(e))
        except OSError as e:
            return cls._metadata_snapshot(server_name, "unreadable", "", message=str(e))
        revision = hashlib.sha256(raw).hexdigest()
        if not raw:
            return cls._metadata_snapshot(server_name, "empty", revision)
        try:
            content = raw.decode("utf-8-sig")
            properties = PropertiesDocumentCodec.parse(content)
        except (UnicodeError, ValueError) as e:
            return cls._metadata_snapshot(server_name, "invalid", revision, message=str(e))
        return cls._snapshot(server_name, "ok", content, properties)

    @classmethod
    def _snapshot(
        cls,
        server_name: str,
        status: ServerPropertiesReadStatus,
        content: str,
        properties: Mapping[str, str],
    ) -> ServerPropertiesSnapshot:
        revision = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls._metadata_snapshot(
            server_name,
            status,
            revision,
            entries=tuple(properties.items()),
        )


__all__ = ["ServerPropertiesStore"]
