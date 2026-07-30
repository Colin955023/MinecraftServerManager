"""
伺服器列表視圖模型 (ServerListViewModel)
提供無頭 (headless) 的伺服器狀態與背景輪詢管理，透過純 Python Callbacks 觸發 UI 更新。
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core import ServerRepository, ServerStartup
from ..models import ServerConfig
from ..utils import get_logger
from .manage_server_service import ManageServerService

logger = get_logger().bind(component="ServerListViewModel")


@dataclass(frozen=True)
class ServerRefreshPayload:
    """背景刷新完成後交給 UI callback 的列表資料載體。"""

    signature: tuple[tuple[str, tuple[Any, ...]], ...]
    server_order: list[str]
    server_rows: dict[str, tuple[Any, ...]]


class ServerListViewModel:
    """負責管理伺服器列表的狀態與背景輪詢。"""

    def __init__(
        self,
        repository: ServerRepository,
        server_startup: ServerStartup,
        get_backup_status_cb: Callable[[str], str],
    ):
        self.repository = repository
        self.server_startup = server_startup
        self.get_backup_status_cb = get_backup_status_cb

        self._callbacks: list[Callable[[ServerRefreshPayload], None]] = []
        self._jar_search_cache: dict[str, Any] = {}
        self._jar_cache_timeout = 60

        self._auto_refresh_enabled = False
        self._auto_refresh_interval_ms = 10000

        self._polling_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._refresh_lock = threading.Lock()

    def add_callback(self, callback: Callable[[ServerRefreshPayload], None]) -> None:
        """註冊狀態變更回呼。

        Args:
            callback: 伺服器狀態更新時要呼叫的回呼函式。
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[ServerRefreshPayload], None]) -> None:
        """移除狀態變更回呼。

        Args:
            callback: 要移除的回呼函式。
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def set_auto_refresh_enabled(self, enabled: bool, *, refresh_now: bool = False) -> None:
        """啟用或停用背景自動重新整理。"""
        self._auto_refresh_enabled = bool(enabled)
        if self._auto_refresh_enabled:
            if not self._polling_thread or not self._polling_thread.is_alive():
                self._start_polling()
            if refresh_now:
                self.refresh_servers(reload_config=True)
        else:
            self._stop_polling()

    def set_auto_refresh_interval(self, interval_ms: int) -> None:
        """設定輪詢間隔 (毫秒)。"""
        self._auto_refresh_interval_ms = interval_ms

    def _start_polling(self) -> None:
        """啟動背景輪詢執行緒。"""
        self._stop_event.clear()
        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True, name="ServerListPoller")
        self._polling_thread.start()

    def _stop_polling(self) -> None:
        """停止背景輪詢執行緒。"""
        self._stop_event.set()
        self._polling_thread = None

    def _polling_loop(self) -> None:
        """背景輪詢迴圈。"""
        while not self._stop_event.is_set():
            if self._auto_refresh_enabled:
                self.refresh_servers(reload_config=False)
            # Sleep in small chunks to allow quick interruption
            for _ in range(max(1, self._auto_refresh_interval_ms // 100)):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

    def refresh_servers(self, reload_config: bool = True) -> None:
        """主動重新整理伺服器狀態。

        Args:
            reload_config: 是否重新載入伺服器設定檔，預設為 True。
        """
        # Prevent overlapping refreshes
        if not self._refresh_lock.acquire(blocking=False):
            return

        try:
            if reload_config:
                self.repository.load_servers_config()

            server_data: list[list[Any]] = []
            if self.repository.servers:
                for name, config in self.repository.servers.items():
                    status = ManageServerService.get_server_status_text(
                        name, config, self.server_startup, self._jar_search_cache, self._jar_cache_timeout
                    )
                    backup_status = self.get_backup_status_cb(name)
                    display_path = self._format_server_path_for_display(config.path)
                    server_data.append(
                        self._build_server_display_row(
                            name=name,
                            config=config,
                            status=status,
                            backup_status=backup_status,
                            display_path=display_path,
                        )
                    )

            payload = self._build_server_refresh_payload(server_data)
            self._notify_observers(payload)

        except Exception as e:
            logger.error(f"重新整理伺服器列表失敗: {e}\n{traceback.format_exc()}", "ServerListViewModel")
        finally:
            self._refresh_lock.release()

    def _notify_observers(self, payload: ServerRefreshPayload) -> None:
        """通知所有已註冊的 callback。"""
        for callback in self._callbacks:
            try:
                callback(payload)
            except Exception as e:
                logger.error(f"執行 ViewModel callback 失敗: {e}", "ServerListViewModel")

    def _format_server_path_for_display(self, raw_path: str) -> str:
        """將絕對路徑轉為易讀的 servers 子路徑形式。"""
        try:
            servers_root = Path(self.repository.servers_root).resolve()
            resolved = Path(raw_path).resolve()
            relative = resolved.relative_to(servers_root)
            return str(Path("servers") / relative)
        except Exception:
            return str(raw_path)

    @staticmethod
    def _format_minecraft_version_display(minecraft_version: str) -> str:
        if minecraft_version and minecraft_version.lower() != "unknown":
            return minecraft_version
        return "未知"

    @staticmethod
    def _format_loader_display(loader_type: str | None, loader_version: str | None) -> str:
        normalized_type = str(loader_type or "").strip().lower()
        normalized_version = str(loader_version or "").strip().lower()
        if not normalized_type or normalized_type == "unknown":
            return "未知"
        display = "原版" if normalized_type == "vanilla" else normalized_type.capitalize()
        if normalized_version and normalized_version != "unknown":
            return f"{display} v{loader_version}"
        return display

    @classmethod
    def _build_server_display_row(
        cls, *, name: str, config: ServerConfig, status: str, backup_status: str, display_path: str
    ) -> list[Any]:
        return [
            name,
            cls._format_minecraft_version_display(config.minecraft_version),
            cls._format_loader_display(config.loader_type, config.loader_version),
            status,
            backup_status,
            display_path,
        ]

    def _build_server_refresh_payload(self, server_data: list[list[Any]]) -> ServerRefreshPayload:
        """將資料建立為 Payload，此邏輯原先位於 ManageServerFrame 內。"""
        server_rows: dict[str, tuple[Any, ...]] = {}
        server_order: list[str] = []
        signature_items: list[tuple[str, tuple[Any, ...]]] = []

        for row in server_data:
            if not row:
                continue
            name = str(row[0])
            row_tuple = tuple(row)
            server_order.append(name)
            server_rows[name] = row_tuple
            signature_items.append((name, row_tuple))

        return ServerRefreshPayload(
            signature=tuple(signature_items), server_order=server_order, server_rows=server_rows
        )

    def shutdown(self) -> None:
        """清理資源，停止輪詢執行緒。"""
        self._stop_polling()
