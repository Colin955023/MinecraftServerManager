"""本地與線上 Tree 同步。"""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path
from typing import Any

from ...models import ModStatus
from ...utils import (
    Colors,
    TreeUtils,
    UIUtils,
    compute_adaptive_pool_limit,
    compute_exponential_moving_average,
)
from ...utils.ui_support import qt_widgets as qt
from .constants import logger
from .online_mod_queue import ModManagementRuntimeBase


class ModManagementTreeSyncMixin(ModManagementRuntimeBase):
    """維護本地與線上 Treeview 的同步、重用與局部刷新。"""

    @staticmethod
    def _get_local_row_palette(is_dark: bool) -> tuple[str, str]:
        """回傳本地模組列表交錯列配色。"""
        if is_dark:
            return (Colors.BG_LISTBOX_DARK, Colors.BG_LISTBOX_ALT_DARK)
        return (Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_ALT_LIGHT)

    @staticmethod
    def _get_parity_tag(index: int) -> str:
        """依列索引回傳交錯底色 tag。"""
        return "odd" if index % 2 == 0 else "even"

    def _extract_or_compute_parity_tag(self, tree: qt.Treeview, item_id: str) -> str:
        """優先沿用現有奇偶 tag，否則依樹狀索引重新計算。"""
        current_tags = list(tree.item(item_id, "tags") or [])
        if len(current_tags) > 1:
            return current_tags[1]
        return self._get_parity_tag(tree.index(item_id))

    @staticmethod
    def _get_tree_item_values(tree: qt.Treeview, item_id: str) -> tuple[Any, ...]:
        """安全取得 Treeview item 的 values。"""
        return tuple(tree.item(item_id, "values") or [])

    @staticmethod
    def _get_tree_item_tags(tree: qt.Treeview, item_id: str) -> tuple[Any, ...]:
        """安全取得 Treeview item 的 tags。"""
        return tuple(tree.item(item_id, "tags") or [])

    @classmethod
    def _get_tree_item_mod_id(cls, tree: qt.Treeview, item_id: str) -> str:
        """從 Treeview item 的 tags 取得模組識別。"""
        tags = cls._get_tree_item_tags(tree, item_id)
        if not tags:
            return ""
        return str(tags[0] or "").strip()

    @classmethod
    def _get_tree_item_mod_name(cls, tree: qt.Treeview, item_id: str) -> str:
        """從 Treeview item 的 values 取得模組名稱。"""
        values = cls._get_tree_item_values(tree, item_id)
        if len(values) < 2:
            return ""
        return str(values[1] or "").strip()

    @staticmethod
    def _build_online_browse_key(mod: Any) -> str:
        """建立線上瀏覽列表使用的穩定識別鍵。"""
        return str(
            getattr(mod, "project_id", "")
            or getattr(mod, "slug", "")
            or getattr(mod, "url", "")
            or getattr(mod, "name", "")
            or ""
        ).strip()

    @staticmethod
    def _format_online_environment_text(mod: Any) -> str:
        """格式化線上模組的支援環境。"""
        server_side = str(getattr(mod, "server_side", "") or "").strip()
        client_side = str(getattr(mod, "client_side", "") or "").strip()
        if client_side and server_side:
            return "兼容（客戶端/伺服器）"
        if client_side:
            return "僅客戶端"
        if server_side:
            return "僅伺服器"
        return "未知"

    def _build_online_browse_row(self, mod: Any) -> tuple[str, str, str, str, str, str]:
        """建立線上瀏覽列表單列顯示內容。"""
        downloads = int(getattr(mod, "download_count", 0) or 0)
        return (
            str(getattr(mod, "name", "未知模組") or "未知模組"),
            str(getattr(mod, "author", "?") or "?"),
            f"{downloads:,}" if downloads > 0 else "N/A",
            self._format_online_result_description(mod),
            str(getattr(mod, "source", "modrinth") or "modrinth").title(),
            self._format_online_environment_text(mod),
        )

    def _clear_online_mods(self) -> None:
        """清空目前線上模組瀏覽結果。"""
        self.online_mods = []
        self._online_mod_index = {}
        self._online_mod_by_row_key = {}
        self._online_rows_snapshot = {}
        self._last_online_request = None
        self._online_refresh_token += 1
        self._cancel_online_refresh_job()
        self.ui_queue.put(self._refresh_online_results_summary)
        self.ui_queue.put(self.refresh_browse_list)

    def _cancel_online_refresh_job(self) -> None:
        """取消尚未完成的線上模組列表批次插入。"""
        tree = self.browse_tree
        if not tree:
            self._online_refresh_job = None
            return
        UIUtils.cancel_scheduled_job(tree, "_online_refresh_job", owner=self)

    def _set_online_tree_render_lock(self, locked: bool) -> None:
        """大量刷新前後鎖住線上 Treeview 父容器幾何，減少 layout 抖動。"""
        tree = self.browse_tree
        if not tree:
            return
        parent = getattr(tree, "master", None)
        if parent is None:
            return
        if locked:
            if getattr(self, "_online_tree_render_locked", False):
                return
            try:
                parent.set_grid_layout_propagation(False)
                self._online_tree_render_locked = True
            except Exception as e:
                logger.debug(f"鎖定線上模組列表渲染失敗: {e}", "ModManagement")
            return
        if not getattr(self, "_online_tree_render_locked", False):
            return
        try:
            parent.set_grid_layout_propagation(True)
        except Exception as e:
            logger.debug(f"解除線上模組列表渲染鎖失敗: {e}", "ModManagement")
        finally:
            self._online_tree_render_locked = False

    def _get_online_insert_batch_size(self, pending_count: int) -> int:
        """依待插入筆數動態計算線上列表批次大小。"""
        if pending_count <= 0:
            return 1
        base = max(1, int(getattr(self, "_online_insert_batch_base", 60)))
        max_size = max(base, int(getattr(self, "_online_insert_batch_max", 180)))
        divisor = max(1, int(getattr(self, "_online_insert_batch_divisor", 8)))
        dynamic_size = max(base, pending_count // divisor)
        dynamic_size = min(dynamic_size, max_size)
        return min(dynamic_size, pending_count)

    def _purge_orphan_online_tree_items(self, expected_item_ids: set[str]) -> None:
        """刪除線上瀏覽 Treeview 中不屬於目前資料的孤兒列。"""
        tree = self.browse_tree
        if not tree or not tree.is_alive():
            return
        for item_id in list(tree.get_children("")):
            if item_id in expected_item_ids:
                continue
            with contextlib.suppress(Exception):
                tree.delete(item_id)

    def _finalize_online_refresh(
        self,
        *,
        refresh_token: int,
        rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]],
        mod_by_row_key: dict[str, Any],
    ) -> None:
        """刷新收尾：只接受最新 token，避免舊任務覆蓋。"""
        if refresh_token != self._online_refresh_token:
            return
        self._online_refresh_job = None
        self._online_rows_snapshot = rows_snapshot
        self._online_mod_by_row_key = mod_by_row_key
        self._set_online_tree_render_lock(False)

    def refresh_browse_list(self) -> None:
        """重新整理線上模組列表（差異更新，避免整棵重建）。"""
        self._refresh_online_results_summary()
        tree = self.browse_tree
        if not tree or not tree.is_alive():
            return
        self._cancel_online_refresh_job()
        self._online_refresh_token += 1
        refresh_token = self._online_refresh_token
        self._set_online_tree_render_lock(True)
        logger.debug(f"重新整理線上模組列表: result_count={len(self.online_mods)}")
        mod_order: list[str] = []
        mod_rows: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        mods_by_row_key: dict[str, Any] = {}
        seen_row_keys: set[str] = set()
        previous_snapshot = getattr(self, "_online_rows_snapshot", {})
        for mod in self.online_mods:
            row_key = self._build_online_browse_key(mod)
            if not row_key or row_key in seen_row_keys:
                continue
            values = self._build_online_browse_row(mod)
            row_tags = (
                str(getattr(mod, "project_id", "") or "").strip(),
                str(getattr(mod, "slug", "") or "").strip(),
                str(getattr(mod, "url", "") or "").strip(),
            )
            mod_order.append(row_key)
            mod_rows[row_key] = (values, row_tags)
            mods_by_row_key[row_key] = mod
            seen_row_keys.add(row_key)

        if not mod_order:
            for item_id in list(tree.get_children("")):
                with contextlib.suppress(Exception):
                    tree.delete(item_id)
            self._finalize_online_refresh(refresh_token=refresh_token, rows_snapshot={}, mod_by_row_key={})
            return

        rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        pending_insert: list[tuple[str, tuple[Any, ...], tuple[str, ...]]] = []
        for row_key in mod_order:
            stored_values, stored_tags = mod_rows[row_key]
            values = stored_values
            tags = stored_tags
            if tree.exists(row_key):
                try:
                    if previous_snapshot.get(row_key) != (values, tags):
                        tree.item(row_key, values=values, tags=tags)
                    rows_snapshot[row_key] = (values, tags)
                    continue
                except Exception as e:
                    logger.debug(f"更新線上列失敗 row_key={row_key}: {e}", "ModManagement")
                    with contextlib.suppress(Exception):
                        tree.delete(row_key)
            pending_insert.append((row_key, values, tags))

        expected_item_ids = set(mod_order)
        self._purge_orphan_online_tree_items(expected_item_ids)
        batch_size = self._get_online_insert_batch_size(len(pending_insert))

        def _finalize_online() -> None:
            try:
                if tree and tree.is_alive():
                    for order_index, row_key in enumerate(mod_order):
                        if tree.exists(row_key):
                            tree.move(row_key, "", order_index)
                    TreeUtils.refresh_treeview_alternating_rows(tree)
            except Exception as e:
                logger.debug(f"重排線上 mods 失敗: {e}", "ModManagement")
            self._finalize_online_refresh(
                refresh_token=refresh_token,
                rows_snapshot=rows_snapshot,
                mod_by_row_key=mods_by_row_key,
            )

        insert_batch = TreeUtils.make_tree_insert_batch(
            tree=tree,
            pending_insert=pending_insert,
            batch_size=batch_size,
            is_refresh_token_valid=lambda: refresh_token == self._online_refresh_token,
            acquire_recycled=lambda _entry: None,
            update_recycled=lambda _item_id, _entry: None,
            insert_new=lambda _idx, entry: tree.insert("", "end", iid=entry[0], values=entry[1], tags=entry[2]),
            set_mapping=lambda _key, _item_id: None,
            mapping_get=lambda key: key if tree.exists(key) else None,
            get_key=lambda entry: entry[0],
            set_row_snapshot=lambda key, values: rows_snapshot.__setitem__(key, values),
            get_order=lambda: mod_order,
            _get_rows=lambda key: mod_rows.get(key),
            finalize_cb=_finalize_online,
            set_refresh_job=lambda v: setattr(self, "_online_refresh_job", v),
            move_item=lambda item_id, idx: tree.move(item_id, "", idx),
            logger_name="ModManagement",
        )
        if pending_insert:
            insert_batch(0, None)
            return
        _finalize_online()

    def _get_enhanced_attr(self, enhanced, attr: str, fallback):
        """屬性值或後備值"""
        if enhanced:
            value = getattr(enhanced, attr, None)
            if value:
                return value
        return fallback

    def _is_exact_local_enhancement_match(self, mod: Any, enhanced: Any) -> bool:
        if not enhanced:
            return False
        platform_id = str(getattr(mod, "platform_id", "") or "").strip().lower()
        enhanced_project_id = str(getattr(enhanced, "project_id", "") or "").strip().lower()
        enhanced_slug = str(getattr(enhanced, "slug", "") or "").strip().lower()
        return bool(platform_id and platform_id in {enhanced_project_id, enhanced_slug})

    def _resolve_local_display_name(self, mod: Any, enhanced: Any) -> str:
        local_name = str(getattr(mod, "name", "") or "").strip()
        if local_name and local_name.lower() not in {"unknown", "unknown mod"}:
            return local_name
        enhanced_name = self._get_enhanced_attr(enhanced, "name", local_name)
        if self._is_exact_local_enhancement_match(mod, enhanced):
            return enhanced_name or local_name
        return local_name or enhanced_name

    def _sync_local_tree_state(self) -> None:
        """把 legacy frame 屬性同步回 LocalTreeVirtualizationState。"""
        state = getattr(self, "local_tree_state", None)
        if state is not None:
            state.capture_from_frame(self)

    def _cancel_local_refresh_job(self) -> None:
        """取消尚未完成的本地模組列表批次插入（共用排程 helper）。"""
        tree = self.local_tree
        if not tree:
            self._local_refresh_job = None
            return
        UIUtils.cancel_scheduled_job(tree, "_local_refresh_job", owner=self)

    def _recycle_local_item(self, item_id: str) -> None:
        """回收不再顯示的 local Tree item，後續可重用。"""
        if not self.local_tree or not item_id:
            return
        try:
            if not self.local_tree.exists(item_id):
                return
            self.local_tree.detach(item_id)
            pool = self._local_recycled_item_ids
            pool.append(item_id)
            max_size = max(0, int(getattr(self, "_local_recycle_pool_max", 500)))
            if len(pool) > max_size:
                stale_id = pool.pop(0)
                self._local_recycle_drops += 1
                with contextlib.suppress(Exception):
                    if self.local_tree.exists(stale_id):
                        self.local_tree.delete(stale_id)
                self._maybe_log_local_recycle_stats()
            self._sync_local_tree_state()
        except Exception as e:
            logger.debug(f"回收 local tree item 失敗 item_id={item_id}: {e}", "ModManagement")

    def _acquire_recycled_local_item(self) -> str | None:
        """從 local 重用池取回可用 item。"""
        tree = self.local_tree
        if not tree:
            return None
        pool = self._local_recycled_item_ids
        while pool:
            candidate = pool.pop()
            with contextlib.suppress(Exception):
                if tree.exists(candidate):
                    self._local_recycle_hits += 1
                    self._maybe_log_local_recycle_stats()
                    self._sync_local_tree_state()
                    return candidate
        self._local_recycle_misses += 1
        self._maybe_log_local_recycle_stats()
        self._sync_local_tree_state()
        return None

    def _maybe_log_local_recycle_stats(self) -> None:
        """定期輸出 local 重用池命中統計（debug），用於調整池大小。"""
        interval = max(1, int(getattr(self, "_local_recycle_log_every", 200)))
        total = int(getattr(self, "_local_recycle_hits", 0)) + int(getattr(self, "_local_recycle_misses", 0))
        if total <= 0 or total % interval != 0:
            return
        raw_hit_rate = self._local_recycle_hits / total * 100.0
        smoothed_hit_rate = compute_exponential_moving_average(
            previous=getattr(self, "_local_recycle_hit_rate_ema", None),
            current=raw_hit_rate,
            alpha=float(getattr(self, "_local_recycle_ema_alpha", 0.35)),
        )
        self._local_recycle_hit_rate_ema = smoothed_hit_rate
        self._auto_tune_local_recycle_pool(smoothed_hit_rate)
        self._sync_local_tree_state()
        message = f"local recycle stats pool={len(self._local_recycled_item_ids)} hits={self._local_recycle_hits} misses={self._local_recycle_misses} drops={self._local_recycle_drops} hit_rate={raw_hit_rate:.1f}% ema={smoothed_hit_rate:.1f}%"
        logger.debug(message, "ModManagement")

    def _auto_tune_local_recycle_pool(self, hit_rate: float) -> None:
        """依命中率自動微調 local recycle pool 上限。"""
        current = max(1, int(getattr(self, "_local_recycle_pool_max", 500)))
        min_size = max(1, int(getattr(self, "_local_recycle_pool_min", 250)))
        cap_size = max(min_size, int(getattr(self, "_local_recycle_pool_cap", 1600)))
        step = max(1, int(getattr(self, "_local_recycle_tune_step", 80)))
        pool_len = len(self._local_recycled_item_ids)
        tune_args = {
            "current": current,
            "min_size": min_size,
            "cap_size": cap_size,
            "step": step,
            "pool_len": pool_len,
            "hit_rate": hit_rate,
        }
        new_size = compute_adaptive_pool_limit(**tune_args)
        if new_size == current:
            return
        self._local_recycle_pool_max = new_size
        self._sync_local_tree_state()
        logger.debug(
            f"自動調整 local recycle pool 上限: {current} -> {new_size} (hit_rate={hit_rate:.1f}%)", "ModManagement"
        )

    def _set_local_tree_render_lock(self, locked: bool) -> None:
        """大量刷新前後鎖住 Treeview 父容器幾何，減少 layout 抖動。"""
        if not self.local_tree:
            return
        parent = self.local_tree.master
        if locked:
            if getattr(self, "_local_tree_render_locked", False):
                return
            try:
                parent.set_grid_layout_propagation(False)
                self._local_tree_render_locked = True
            except Exception as e:
                logger.debug(f"鎖定 local tree 渲染失敗: {e}", "ModManagement")
            return
        if not getattr(self, "_local_tree_render_locked", False):
            return
        try:
            parent.set_grid_layout_propagation(True)
        except Exception as e:
            logger.debug(f"解除 local tree 渲染鎖失敗: {e}", "ModManagement")
        finally:
            self._local_tree_render_locked = False

    def _get_local_insert_batch_size(self, pending_count: int) -> int:
        """依待插入筆數動態計算 local list 批次大小。"""
        if pending_count <= 0:
            return 1
        base = max(1, int(getattr(self, "_local_insert_batch_base", 60)))
        max_size = max(base, int(getattr(self, "_local_insert_batch_max", 180)))
        divisor = max(1, int(getattr(self, "_local_insert_batch_divisor", 8)))
        dynamic_size = max(base, pending_count // divisor)
        dynamic_size = min(dynamic_size, max_size)
        return min(dynamic_size, pending_count)

    def _capture_selected_mod_ids(self) -> set[str]:
        """擷取目前選取列對應的 mod id（Treeview tag[0]）。"""
        if not self.local_tree:
            return set()
        selected_mod_ids: set[str] = set()
        for item_id in self.local_tree.selection():
            tags = self.local_tree.item(item_id, "tags")
            if tags:
                selected_mod_ids.add(str(tags[0]))
        return selected_mod_ids

    def _restore_local_selection(self, selected_mod_ids: set[str]) -> None:
        """刷新後回復多選狀態。"""
        if not self.local_tree:
            return
        selected_items = [
            item_id for mod_id in selected_mod_ids for item_id in [self._local_item_by_mod_id.get(mod_id)] if item_id
        ]
        if selected_items:
            with contextlib.suppress(Exception):
                self.local_tree.selection_set(selected_items)
                self.local_tree.see(selected_items[0])

    def _finalize_local_refresh(
        self,
        *,
        refresh_token: int,
        rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]],
        selected_mod_ids: set[str],
    ) -> None:
        """刷新收尾：只接受最新 token，避免舊任務覆蓋。"""
        if refresh_token != self._local_refresh_token:
            return
        self._local_refresh_job = None
        self._local_rows_snapshot = rows_snapshot
        self._sync_local_tree_state()
        self._restore_local_selection(selected_mod_ids)
        self.on_tree_selection_changed()
        self._set_local_tree_render_lock(False)
        self._sync_local_tree_state()

    def _purge_orphan_local_tree_items(self, expected_item_ids: set[str]) -> None:
        """刪除 Treeview 中不屬於目前映射表的孤兒列，避免重複顯示。"""
        tree = self.local_tree
        if not tree or not tree.is_alive():
            return
        recycled_pool = set(self._local_recycled_item_ids)
        active_children = list(tree.get_children(""))
        for item_id in active_children:
            if item_id in expected_item_ids:
                continue
            with contextlib.suppress(Exception):
                tree.delete(item_id)
        if recycled_pool:
            self._local_recycled_item_ids = [
                item_id for item_id in self._local_recycled_item_ids if tree.exists(item_id)
            ]
        self._sync_local_tree_state()

    def _apply_local_tree_diff(
        self,
        *,
        mod_order: list[str],
        mod_rows: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]],
        refresh_token: int,
        selected_mod_ids: set[str],
    ) -> None:
        """以差異更新本地模組 Treeview，避免整棵重建。"""
        tree = self.local_tree
        if not tree or not tree.is_alive():
            self._set_local_tree_render_lock(False)
            return
        for mod_id, stale_item_id in list(self._local_item_by_mod_id.items()):
            if mod_id in mod_rows:
                continue
            self._recycle_local_item(stale_item_id)
            self._local_item_by_mod_id.pop(mod_id, None)
        rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        pending_insert: list[tuple[str, tuple[Any, ...], tuple[str, ...]]] = []
        previous_snapshot = getattr(self, "_local_rows_snapshot", {})
        for mod_id in mod_order:
            values, tags = mod_rows[mod_id]
            item_id = self._local_item_by_mod_id.get(mod_id)
            if item_id:
                try:
                    if previous_snapshot.get(mod_id) != (values, tags):
                        tree.item(item_id, values=values, tags=tags)
                    rows_snapshot[mod_id] = (values, tags)
                    continue
                except Exception as e:
                    logger.debug(f"更新本地列失敗 mod_id={mod_id}: {e}", "ModManagement")
                    self._recycle_local_item(item_id)
                    self._local_item_by_mod_id.pop(mod_id, None)
            pending_insert.append((mod_id, values, tags))
        if not mod_order:
            self._local_item_by_mod_id.clear()
            self._finalize_local_refresh(refresh_token=refresh_token, rows_snapshot={}, selected_mod_ids=set())
            return
        batch_size = self._get_local_insert_batch_size(len(pending_insert))

        def _update_recycled(item_id: str, entry: tuple) -> None:
            tree.item(item_id, values=entry[1], tags=entry[2])
            tree.reattach(item_id, "", "end")

        def _finalize_local() -> None:
            self._purge_orphan_local_tree_items(
                {item_id for mod_id in mod_order for item_id in [self._local_item_by_mod_id.get(mod_id)] if item_id}
            )
            self._finalize_local_refresh(
                refresh_token=refresh_token, rows_snapshot=rows_snapshot, selected_mod_ids=selected_mod_ids
            )

        insert_batch = TreeUtils.make_tree_insert_batch(
            tree=tree,
            pending_insert=pending_insert,
            batch_size=batch_size,
            is_refresh_token_valid=lambda: refresh_token == self._local_refresh_token,
            acquire_recycled=lambda _entry: self._acquire_recycled_local_item(),
            update_recycled=_update_recycled,
            insert_new=lambda _idx, entry: tree.insert("", "end", values=entry[1], tags=entry[2]),
            set_mapping=lambda key, item_id: self._local_item_by_mod_id.__setitem__(key, item_id),
            mapping_get=lambda key: self._local_item_by_mod_id.get(key),
            get_key=lambda entry: entry[0],
            set_row_snapshot=lambda key, values: rows_snapshot.__setitem__(key, values),
            get_order=lambda: mod_order,
            _get_rows=lambda key: mod_rows.get(key),
            finalize_cb=_finalize_local,
            set_refresh_job=lambda v: setattr(self, "_local_refresh_job", v),
            move_item=lambda item_id, idx: tree.move(item_id, "", idx),
            logger_name="ModManagement",
        )
        if pending_insert:
            insert_batch(0, None)
            return
        try:
            for order_index, mod_id in enumerate(mod_order):
                item_id = self._local_item_by_mod_id.get(mod_id)
                if item_id:
                    tree.move(item_id, "", order_index)
                    rows_snapshot[mod_id] = mod_rows[mod_id]
            expected_item_ids = {
                item_id for mod_id in mod_order for item_id in [self._local_item_by_mod_id.get(mod_id)] if item_id
            }
            self._purge_orphan_local_tree_items(expected_item_ids)
        except Exception as e:
            logger.debug(f"重排 local mods 失敗: {e}", "ModManagement")
        self._finalize_local_refresh(
            refresh_token=refresh_token, rows_snapshot=rows_snapshot, selected_mod_ids=selected_mod_ids
        )

    def refresh_local_list(self) -> None:
        """重新整理本地模組列表（差異更新，避免整棵重建）。"""
        if not hasattr(self, "local_tree") or not self.local_tree:
            return
        self._cancel_local_refresh_job()
        self._local_refresh_token += 1
        refresh_token = self._local_refresh_token
        selected_mod_ids = self._capture_selected_mod_ids()
        self._set_local_tree_render_lock(True)
        search_text = self.local_search_var.get() if hasattr(self, "local_search_var") else ""
        search_filter = getattr(self, "local_search_filter", None)
        filter_status = self.local_filter_var.get() if hasattr(self, "local_filter_var") else "所有"
        version_pattern = self.VERSION_PATTERN
        mod_order: list[str] = []
        mod_rows: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        seen_mod_ids: set[str] = set()
        for mod in self.local_mods:
            mod_name = str(getattr(mod, "name", "") or "")
            search_candidate = (
                mod_name,
                getattr(mod, "filename", ""),
                getattr(mod, "version", ""),
                getattr(mod, "author", ""),
            )
            if search_text and search_filter is not None and not search_filter.matches(search_candidate, search_text):
                continue
            if search_text and search_filter is None and str(search_text).lower() not in mod_name.lower():
                continue
            if filter_status != "所有" and (
                (filter_status == "啟用" and mod.status != ModStatus.ENABLED)
                or (filter_status == "停用" and mod.status != ModStatus.DISABLED)
            ):
                continue
            enhanced = self.enhanced_mods_cache.get(mod.filename)
            parsed_version = "未知"
            m = version_pattern.search(mod.filename)
            if m:
                parsed_version = m.group(1)
            display_name = self._resolve_local_display_name(mod, enhanced)
            display_author = self._get_enhanced_attr(enhanced, "author", mod.author or "Unknown")
            if mod.version and mod.version not in ("", "未知"):
                display_version = mod.version
            elif enhanced:
                enhanced_version = getattr(enhanced, "version", None)
                enhanced_versions = getattr(enhanced, "versions", None)
                if enhanced_version:
                    display_version = enhanced_version
                elif enhanced_versions:
                    display_version = (
                        enhanced_versions[0]
                        if isinstance(enhanced_versions, list) and enhanced_versions
                        else str(enhanced_versions)
                    )
                elif parsed_version and parsed_version not in ("", "未知"):
                    display_version = parsed_version
                else:
                    display_version = "未知"
            elif parsed_version and parsed_version not in ("", "未知"):
                display_version = parsed_version
            else:
                display_version = "未知"
            display_description = self._format_single_line_text(
                self._get_enhanced_attr(enhanced, "description", mod.description or "")
            )
            status_text = "✅ 已啟用" if mod.status == ModStatus.ENABLED else "❌ 已停用"
            mod_base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
            size_val = getattr(mod, "file_size", 0)
            if size_val >= 1024 * 1024:
                display_size = f"{size_val / 1024 / 1024:.1f} MB"
            elif size_val >= 1024:
                display_size = f"{size_val / 1024:.1f} KB"
            else:
                display_size = f"{size_val} B"
            mtime_val = getattr(mod, "_cached_mtime", None)
            if mtime_val is None:
                try:
                    mtime_val = Path(mod.file_path).stat().st_mtime
                    mod._cached_mtime = mtime_val
                except Exception:
                    mtime_val = None
            display_mtime = datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M") if mtime_val else "未知"
            if mod_base_name in seen_mod_ids:
                continue
            seen_mod_ids.add(mod_base_name)
            parity_tag = self._get_parity_tag(len(mod_order))
            values: tuple[Any, ...] = (
                status_text,
                display_name,
                display_version,
                display_author,
                mod.loader_type,
                display_size,
                display_mtime,
                display_description,
            )
            tags = (mod_base_name, parity_tag)
            mod_order.append(mod_base_name)
            mod_rows[mod_base_name] = (values, tags)
        self._apply_local_tree_diff(
            mod_order=mod_order, mod_rows=mod_rows, refresh_token=refresh_token, selected_mod_ids=selected_mod_ids
        )


__all__ = ["ModManagementTreeSyncMixin"]
