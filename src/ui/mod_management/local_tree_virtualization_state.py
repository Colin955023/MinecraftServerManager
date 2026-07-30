"""Treeview 虛擬化狀態與快取（通用）。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

RowSnapshot = tuple[tuple[Any, ...], tuple[str, ...]]
VisibleItem = tuple[str, str, RowSnapshot | None]


@dataclass
class TreeVirtualizationState:
    """集中管理 Treeview 列表的增量渲染、回收池與快照狀態。

    可透過 `prefix` 參數適配不同 frame 的屬性命名慣例：
    - 本地模組列表：`prefix="_local"`
    - 伺服器列表：`prefix="_server"`
    """

    refresh_job: str | None = None
    refresh_token: int = 0
    filter_job: Any | None = None
    tree_render_locked: bool = False
    item_by_mod_id: dict[str, str] = field(default_factory=dict)
    rows_snapshot: dict[str, RowSnapshot] = field(default_factory=dict)
    recycled_item_ids: list[str] = field(default_factory=list)
    recycle_pool_max: int = 500
    recycle_hits: int = 0
    recycle_misses: int = 0
    recycle_drops: int = 0
    recycle_log_every: int = 200
    recycle_pool_min: int = 250
    recycle_pool_cap: int = 1600
    recycle_tune_step: int = 80
    recycle_hit_rate_ema: float | None = None
    recycle_ema_alpha: float = 0.35
    insert_batch_base: int = 60
    insert_batch_max: int = 180
    insert_batch_divisor: int = 8

    _FIELD_TO_FRAME_SUFFIX: dict[str, str] = field(
        default_factory=lambda: {
            "refresh_job": "refresh_job",
            "refresh_token": "refresh_token",  # nosec B105
            "filter_job": "filter_job",
            "tree_render_locked": "tree_render_locked",
            "item_by_mod_id": "item_by_mod_id",
            "rows_snapshot": "rows_snapshot",
            "recycled_item_ids": "recycled_item_ids",
            "recycle_pool_max": "recycle_pool_max",
            "recycle_hits": "recycle_hits",
            "recycle_misses": "recycle_misses",
            "recycle_drops": "recycle_drops",
            "recycle_log_every": "recycle_log_every",
            "recycle_pool_min": "recycle_pool_min",
            "recycle_pool_cap": "recycle_pool_cap",
            "recycle_tune_step": "recycle_tune_step",
            "recycle_hit_rate_ema": "recycle_hit_rate_ema",
            "recycle_ema_alpha": "recycle_ema_alpha",
            "insert_batch_base": "insert_batch_base",
            "insert_batch_max": "insert_batch_max",
            "insert_batch_divisor": "insert_batch_divisor",
        },
        init=False,
        repr=False,
        hash=False,
        compare=False,
    )

    def _frame_attr(self, field_name: str, prefix: str) -> str:
        """組合 frame 屬性名稱。"""
        suffix = self._FIELD_TO_FRAME_SUFFIX.get(field_name, field_name)
        return f"{prefix}_{suffix}"

    def apply_to_frame(self, frame: Any, *, prefix: str = "_local") -> None:
        """
        把狀態掛回既有 frame 屬性，維持現有 mixin 呼叫相容。

        Args:
            frame: 具有對應屬性的 UI frame 物件。
            prefix: 屬性前綴（如 ``_local`` 或 ``_server``）。
        """
        for field_name in self._FIELD_TO_FRAME_SUFFIX:
            setattr(frame, self._frame_attr(field_name, prefix), getattr(self, field_name))

    def capture_from_frame(self, frame: Any, *, prefix: str = "_local") -> None:
        """
        從既有 frame 屬性同步最新狀態，供漸進式遷移使用。

        Args:
            frame: 具有對應屬性的 UI frame 物件。
            prefix: 屬性前綴（如 "_local" 或 "_server"）。
        """
        for field_name in self._FIELD_TO_FRAME_SUFFIX:
            current = getattr(self, field_name)
            frame_value = getattr(frame, self._frame_attr(field_name, prefix), current)
            if isinstance(current, bool) and not isinstance(frame_value, bool):
                frame_value = bool(frame_value)
            elif isinstance(current, int) and not isinstance(frame_value, int):
                try:
                    frame_value = int(frame_value)
                except TypeError, ValueError:
                    frame_value = current
            elif isinstance(current, float) and not isinstance(frame_value, float):
                try:
                    frame_value = float(frame_value)
                except TypeError, ValueError:
                    frame_value = current
            setattr(self, field_name, frame_value)

    def update_snapshot(
        self,
        *,
        rows_snapshot: dict[str, RowSnapshot] | None = None,
        item_by_mod_id: dict[str, str] | None = None,
        recycled_item_ids: Iterable[str] | None = None,
        refresh_token: int | None = None,
    ) -> None:
        """
        更新目前渲染快照與可見 item 對應。

        Args:
            rows_snapshot: 最新的 id 到列快照對應。
            item_by_mod_id: 最新的 id 到 Tree item id 對應。
            recycled_item_ids: 最新的 Tree item id 回收池列表。
            refresh_token: 觸發更新的 token，供外部追蹤變更來源。
        """
        if rows_snapshot is not None:
            self.rows_snapshot = rows_snapshot
        if item_by_mod_id is not None:
            self.item_by_mod_id = item_by_mod_id
        if recycled_item_ids is not None:
            self.recycled_item_ids = list(recycled_item_ids)
        if refresh_token is not None:
            self.refresh_token = refresh_token

    def reset_snapshot(self) -> None:
        """清空目前 Treeview 快照與重用池。"""
        self.item_by_mod_id.clear()
        self.rows_snapshot.clear()
        self.recycled_item_ids.clear()

    def get_visible_items(self) -> list[VisibleItem]:
        """回傳目前可見的 id、Tree item id 與列快照。"""
        return [
            (item_id_key, item_id, self.rows_snapshot.get(item_id_key))
            for item_id_key, item_id in self.item_by_mod_id.items()
            if item_id not in self.recycled_item_ids
        ]


__all__ = [
    "RowSnapshot",
    "TreeVirtualizationState",
    "VisibleItem",
]
