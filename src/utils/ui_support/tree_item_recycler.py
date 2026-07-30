"""
TreeView 項目回收池效能管理器
將回收池命中率計算、EMA 指數移動平均與池大小動態調整邏輯抽離為獨立元件。
"""

from __future__ import annotations

import contextlib
from typing import Any

from .. import (
    compute_adaptive_pool_limit,
    compute_exponential_moving_average,
    get_logger,
)

logger = get_logger().bind(component="TreeItemRecycler")


class TreeItemRecycler:
    """管理 TreeView 項目的回收池與效能監控。"""

    def __init__(
        self,
        tree: Any,
        pool_min: int = 150,
        pool_max: int = 300,
        pool_cap: int = 1200,
        tune_step: int = 50,
        log_every: int = 200,
        ema_alpha: float = 0.35,
    ):
        """
        初始化回收池。

        Args:
            tree: 綁定的 TreeView 實例。
            pool_min: 池的最小容量。
            pool_max: 池的初始最大容量。
            pool_cap: 池的絕對上限容量。
            tune_step: 每次自動調整的增減幅度。
            log_every: 多少次存取後執行一次日誌輸出與池大小調整。
            ema_alpha: EMA 平滑係數。
        """
        self.tree = tree
        self._recycled_item_ids: list[str] = []
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool_cap = pool_cap
        self._tune_step = tune_step
        self._log_every = log_every
        self._ema_alpha = ema_alpha

        self._hits = 0
        self._misses = 0
        self._drops = 0
        self._hit_rate_ema: float | None = None

    def recycle_item(self, item_id: str) -> None:
        """
        回收指定的 Tree item。

        Args:
            item_id: 要回收的 item ID。
        """
        try:
            if not getattr(self.tree, "exists", lambda _: False)(item_id):
                return
            self.tree.detach(item_id)
            self._recycled_item_ids.append(item_id)

            if len(self._recycled_item_ids) > max(0, self._pool_max):
                stale_id = self._recycled_item_ids.pop(0)
                self._drops += 1
                with contextlib.suppress(Exception):
                    if getattr(self.tree, "exists", lambda _: False)(stale_id):
                        self.tree.delete(stale_id)
                self._maybe_log_stats()
        except Exception as e:
            logger.debug(f"回收 tree item 失敗 item_id={item_id}: {e}", "TreeItemRecycler")

    def acquire_item(self) -> str | None:
        """
        從重用池取回可用的 Tree item。

        Returns:
            若有可用的 item ID 則返回，否則返回 None。
        """
        if not self.tree:
            return None
        while self._recycled_item_ids:
            candidate = self._recycled_item_ids.pop()
            with contextlib.suppress(Exception):
                if getattr(self.tree, "exists", lambda _: False)(candidate):
                    self._hits += 1
                    self._maybe_log_stats()
                    return candidate
        self._misses += 1
        self._maybe_log_stats()
        return None

    def _maybe_log_stats(self) -> None:
        """定期輸出重用池命中統計（debug），並自動調整池大小。"""
        interval = max(1, self._log_every)
        total = self._hits + self._misses
        if total <= 0 or total % interval != 0:
            return

        raw_hit_rate = self._hits / total * 100.0
        smoothed_hit_rate = compute_exponential_moving_average(
            previous=self._hit_rate_ema,
            current=raw_hit_rate,
            alpha=self._ema_alpha,
        )
        self._hit_rate_ema = smoothed_hit_rate
        self._auto_tune_pool(smoothed_hit_rate)

        message = (
            f"recycle stats pool={len(self._recycled_item_ids)} "
            f"hits={self._hits} misses={self._misses} drops={self._drops} "
            f"hit_rate={raw_hit_rate:.1f}% ema={smoothed_hit_rate:.1f}%"
        )
        logger.debug(message, "TreeItemRecycler")

    def _auto_tune_pool(self, hit_rate: float) -> None:
        """依命中率自動微調 recycle pool 上限。"""
        current = max(1, self._pool_max)
        min_size = max(1, self._pool_min)
        cap_size = max(min_size, self._pool_cap)
        step = max(1, self._tune_step)
        pool_len = len(self._recycled_item_ids)

        new_size = compute_adaptive_pool_limit(
            current=current, min_size=min_size, cap_size=cap_size, step=step, pool_len=pool_len, hit_rate=hit_rate
        )
        if new_size != current:
            self._pool_max = new_size
            logger.debug(
                f"自動調整 recycle pool 上限: {current} -> {new_size} (hit_rate={hit_rate:.1f}%)",
                "TreeItemRecycler",
            )
