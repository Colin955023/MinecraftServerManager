"""本地模組 Treeview 虛擬化狀態與快取。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

LocalRowSnapshot = tuple[tuple[Any, ...], tuple[str, ...]]
VisibleLocalItem = tuple[str, str, LocalRowSnapshot | None]


@dataclass
class LocalTreeVirtualizationState:
    """集中管理本地模組列表的增量渲染、回收池與快照狀態。"""

    refresh_job: str | None = None
    refresh_token: int = 0
    filter_job: Any | None = None
    tree_render_locked: bool = False
    item_by_mod_id: dict[str, str] = field(default_factory=dict)
    rows_snapshot: dict[str, LocalRowSnapshot] = field(default_factory=dict)
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

    def apply_to_frame(self, frame: Any) -> None:
        """
        把狀態掛回既有 frame 屬性，維持現有 mixin 呼叫相容。

        Args:
            frame: 具有對應屬性的 UI frame 物件。
        """
        frame._local_refresh_job = self.refresh_job
        frame._local_refresh_token = self.refresh_token
        frame._local_filter_job = self.filter_job
        frame._local_tree_render_locked = self.tree_render_locked
        frame._local_item_by_mod_id = self.item_by_mod_id
        frame._local_rows_snapshot = self.rows_snapshot
        frame._local_recycled_item_ids = self.recycled_item_ids
        frame._local_recycle_pool_max = self.recycle_pool_max
        frame._local_recycle_hits = self.recycle_hits
        frame._local_recycle_misses = self.recycle_misses
        frame._local_recycle_drops = self.recycle_drops
        frame._local_recycle_log_every = self.recycle_log_every
        frame._local_recycle_pool_min = self.recycle_pool_min
        frame._local_recycle_pool_cap = self.recycle_pool_cap
        frame._local_recycle_tune_step = self.recycle_tune_step
        frame._local_recycle_hit_rate_ema = self.recycle_hit_rate_ema
        frame._local_recycle_ema_alpha = self.recycle_ema_alpha
        frame._local_insert_batch_base = self.insert_batch_base
        frame._local_insert_batch_max = self.insert_batch_max
        frame._local_insert_batch_divisor = self.insert_batch_divisor

    def capture_from_frame(self, frame: Any) -> None:
        """
        從既有 frame 屬性同步最新狀態，供漸進式遷移使用。

        Args:
            frame: 具有對應屬性的 UI frame 物件。
        """
        self.refresh_job = getattr(frame, "_local_refresh_job", self.refresh_job)
        self.refresh_token = int(getattr(frame, "_local_refresh_token", self.refresh_token))
        self.filter_job = getattr(frame, "_local_filter_job", self.filter_job)
        self.tree_render_locked = bool(getattr(frame, "_local_tree_render_locked", self.tree_render_locked))
        self.item_by_mod_id = getattr(frame, "_local_item_by_mod_id", self.item_by_mod_id)
        self.rows_snapshot = getattr(frame, "_local_rows_snapshot", self.rows_snapshot)
        self.recycled_item_ids = getattr(frame, "_local_recycled_item_ids", self.recycled_item_ids)
        self.recycle_pool_max = int(getattr(frame, "_local_recycle_pool_max", self.recycle_pool_max))
        self.recycle_hits = int(getattr(frame, "_local_recycle_hits", self.recycle_hits))
        self.recycle_misses = int(getattr(frame, "_local_recycle_misses", self.recycle_misses))
        self.recycle_drops = int(getattr(frame, "_local_recycle_drops", self.recycle_drops))
        self.recycle_log_every = int(getattr(frame, "_local_recycle_log_every", self.recycle_log_every))
        self.recycle_pool_min = int(getattr(frame, "_local_recycle_pool_min", self.recycle_pool_min))
        self.recycle_pool_cap = int(getattr(frame, "_local_recycle_pool_cap", self.recycle_pool_cap))
        self.recycle_tune_step = int(getattr(frame, "_local_recycle_tune_step", self.recycle_tune_step))
        self.recycle_hit_rate_ema = getattr(frame, "_local_recycle_hit_rate_ema", self.recycle_hit_rate_ema)
        self.recycle_ema_alpha = float(getattr(frame, "_local_recycle_ema_alpha", self.recycle_ema_alpha))
        self.insert_batch_base = int(getattr(frame, "_local_insert_batch_base", self.insert_batch_base))
        self.insert_batch_max = int(getattr(frame, "_local_insert_batch_max", self.insert_batch_max))
        self.insert_batch_divisor = int(getattr(frame, "_local_insert_batch_divisor", self.insert_batch_divisor))

    def update_snapshot(
        self,
        *,
        rows_snapshot: dict[str, LocalRowSnapshot] | None = None,
        item_by_mod_id: dict[str, str] | None = None,
        recycled_item_ids: Iterable[str] | None = None,
        refresh_token: int | None = None,
    ) -> None:
        """
        更新目前渲染快照與可見 item 對應。


        Args:
            rows_snapshot: 最新的 mod id 到列快照對應。
            item_by_mod_id: 最新的 mod id 到 Tree item id 對應。
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

    def get_visible_items(self) -> list[VisibleLocalItem]:
        """回傳目前可見的 mod id、Tree item id 與列快照。"""
        return [
            (mod_id, item_id, self.rows_snapshot.get(mod_id))
            for mod_id, item_id in self.item_by_mod_id.items()
            if item_id not in self.recycled_item_ids
        ]


__all__ = ["LocalRowSnapshot", "LocalTreeVirtualizationState", "VisibleLocalItem"]
