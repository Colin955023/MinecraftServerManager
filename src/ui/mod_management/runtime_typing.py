"""mod_management mixin 共用型別底座。"""

from __future__ import annotations

import queue
import tkinter.ttk as ttk
from re import Pattern
from typing import Any

from .models import OnlineBrowseRequest, PendingOnlineInstall


class ModManagementRuntimeBase:
    """為拆分後的 mixin 提供共同宿主屬性型別。"""

    parent: Any
    current_server: Any | None
    mod_manager: Any | None
    notebook: Any | None
    browse_tree: ttk.Treeview | None
    browse_filter_label: Any | None
    browse_results_label: Any | None
    browse_sort_var: Any
    browse_sort_options: dict[str, str]
    local_tree: ttk.Treeview | None
    local_mods: list[Any]
    online_mods: list[Any]
    pending_online_installs: list[PendingOnlineInstall]
    ui_queue: queue.Queue[Any]
    enhanced_mods_cache: dict[str, Any]
    VERSION_PATTERN: Pattern[str]
    _last_online_request: OnlineBrowseRequest | None
    _online_refresh_job: str | None
    _online_refresh_token: int
    _online_tree_render_locked: bool
    _online_rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]]
    _online_mod_by_row_key: dict[str, Any]
    _online_mod_index: dict[str, Any]
    _local_refresh_job: str | None
    _local_refresh_token: int
    _local_item_by_mod_id: dict[str, str]
    _local_recycled_item_ids: list[str]
    _local_recycle_hits: int
    _local_recycle_misses: int
    _local_recycle_drops: int
    _local_recycle_hit_rate_ema: float | None

    def __getattr__(self, _name: str) -> Any:
        """將未明確宣告的宿主成員視為 `Any`。"""
        raise AttributeError(_name)
