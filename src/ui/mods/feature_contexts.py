"""模組管理 feature 使用的窄執行期 context"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .mod_management_session import ModManagementSession


@dataclass(slots=True)
class ModManagementFeatureContext:
    """提供 feature 所需的 state、effect 與 widget port，不暴露主框架"""

    parent: Any
    server_manager: Any
    mod_planning: Any
    mod_provider: Any
    loader_manager: Any
    mod_session: ModManagementSession
    main_frame: Any = None
    local_tab: Any = None
    browse_tab: Any = None
    mod_manager: Any = None
    scope: Any = None
    local_mod_list_presenter: Any = None
    online_browse_presenter: Any = None
    queue_ops: Any = None
    review_ops: Any = None
    install_executor: Any = None
    tree_sync: Any = None
    notebook: Any = None
    status_label: Any = None
    status_sink: Callable[[str], None] | None = None
    status_async_sink: Callable[[str], None] | None = None
    progress_sink: Callable[[float], None] | None = None
    toggle_success_sink: Callable[..., None] | None = None
    refresh_online_queue: Callable[[], None] | None = None
    refresh_online_filter_hint: Callable[[], None] | None = None
    refresh_online_results_summary: Callable[[], None] | None = None
    clear_online_results: Callable[[], None] | None = None
    format_online_environment: Callable[[Any], str] | None = None
    open_project_page: Callable[..., None] | None = None
    capture_selected_mod_ids: Callable[[], set[str]] | None = None
    get_current_modrinth_context: Callable[[], tuple[str | None, str | None, str | None]] | None = None

    def update_status(self, message: str) -> None:
        """
        將同步狀態訊息交給 composition root 的 sink

        Args:
            message: 要顯示的狀態訊息
        """
        if self.status_sink is not None:
            self.status_sink(message)

    def update_status_safe(self, message: str) -> None:
        """
        將背景工作狀態訊息交給 UI 執行緒 sink

        Args:
            message: 要顯示的狀態訊息
        """
        if self.status_async_sink is not None:
            self.status_async_sink(message)
        else:
            self.update_status(message)

    def update_progress_safe(self, value: float) -> None:
        """
        將背景工作進度交給 UI sink

        Args:
            value: 介於 0.0 與 1.0 的進度值
        """
        if self.progress_sink is not None:
            self.progress_sink(value)

    def apply_local_toggle_success(self, **kwargs: Any) -> None:
        """
        通知本地模組狀態切換已成功

        Args:
            **kwargs: 本地模組切換結果的具名欄位
        """
        if self.toggle_success_sink is not None:
            self.toggle_success_sink(**kwargs)


__all__ = ["ModManagementFeatureContext"]
