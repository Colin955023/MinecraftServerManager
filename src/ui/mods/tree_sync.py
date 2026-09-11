"""本地與線上 Tree 同步"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidgetItem
from qfluentwidgets import isDarkTheme

from src.models import ModStatus
from src.ui import (
    Colors,
    resolve_color,
)

from .constants import logger
from .feature_contexts import ModManagementFeatureContext
from .mod_management_session import ModListRow
from .mod_presentation import format_single_line_text


class ModManagementTreeSyncOps:
    """維護本地與線上模組列表的同步與刷新"""

    VERSION_PATTERN = re.compile("-([\\dv.]+)(?:\\.jar(?:\\.disabled)?)?$")

    def __init__(self, context: ModManagementFeatureContext) -> None:
        self.controller = context
        self._local_items: dict[str, QTreeWidgetItem] = {}

    @staticmethod
    def _build_online_browse_key(mod: Any) -> str:
        """建立線上瀏覽列表使用的穩定識別鍵"""
        return str(
            getattr(mod, "project_id", "")
            or getattr(mod, "slug", "")
            or getattr(mod, "url", "")
            or getattr(mod, "name", "")
            or ""
        ).strip()

    @staticmethod
    def format_online_environment_text(mod: Any) -> str:
        """
        格式化線上模組的支援環境

        Args:
            mod: 線上模組資料

        Returns:
            可供 UI 顯示的支援環境文字
        """
        server_side = str(getattr(mod, "server_side", "") or "").strip()
        client_side = str(getattr(mod, "client_side", "") or "").strip()
        if client_side and server_side:
            return "相容（客戶端/伺服器）"
        if client_side:
            return "僅客戶端"
        if server_side:
            return "僅伺服器"
        return "未知"

    def refresh_browse_list(self) -> None:
        """重新整理線上模組列表"""
        if self.controller.refresh_online_results_summary is not None:
            self.controller.refresh_online_results_summary()
        tree = self.controller.online_browse_presenter.browse_tree
        if not tree:
            return

        online_mods = self.controller.mod_session.online_mods
        logger.debug(f"重新整理線上模組列表: result_count={len(online_mods)}")

        projections: list[ModListRow] = []
        seen_row_keys: set[str] = set()

        for mod in online_mods:
            row_key = self._build_online_browse_key(mod)
            if not row_key or row_key in seen_row_keys:
                continue
            values = self._build_online_browse_row(mod)
            row_tags = (
                str(getattr(mod, "project_id", "") or "").strip(),
                str(getattr(mod, "slug", "") or "").strip(),
                str(getattr(mod, "url", "") or "").strip(),
            )
            projections.append(ModListRow(row_key, tuple(str(value) for value in values), row_tags))
            seen_row_keys.add(row_key)

        self.controller.mod_session.replace_online_rows(projections)

        tree.clear()

        items = []
        for row in self.controller.mod_session.snapshot().online_rows:
            item = QTreeWidgetItem(list(row.values))
            item.setData(0, Qt.ItemDataRole.UserRole, row.data)
            items.append(item)

        if items:
            tree.addTopLevelItems(items)

    def refresh_local_list(self, preserve_selection: bool = True) -> None:
        """
        重新整理本地模組列表

        Args:
            preserve_selection: 是否保留目前的選取項目狀態
        """
        presenter = self.controller.local_mod_list_presenter
        tree = presenter.local_tree
        if not tree:
            return

        selected_mod_ids = self.capture_selected_mod_ids() if preserve_selection else set()

        projections: list[ModListRow] = []
        seen_mod_ids: set[str] = set()

        for mod in self.controller.mod_session.local_mods:
            enhanced = self.controller.mod_session.get_provider_cache(mod.filename)
            parsed_version = "未知"
            match = self.VERSION_PATTERN.search(mod.filename)
            if match:
                parsed_version = match.group(1)

            display_name = self._resolve_local_display_name(mod, enhanced)
            local_author = str(mod.author or "").strip()
            display_author = local_author or self._get_enhanced_attr(enhanced, "author", "Unknown")

            if mod.version and mod.version not in ("", "未知"):
                display_version = mod.version
            elif enhanced:
                enhanced_version = getattr(enhanced, "version", None)
                if enhanced_version:
                    display_version = enhanced_version
                elif parsed_version and parsed_version not in ("", "未知"):
                    display_version = parsed_version
                else:
                    display_version = "未知"
            elif parsed_version and parsed_version not in ("", "未知"):
                display_version = parsed_version
            else:
                display_version = "未知"

            local_description = str(mod.description or "").strip()
            raw_desc = local_description or self._get_enhanced_attr(enhanced, "description", "")
            display_description = format_single_line_text(raw_desc)

            status_text = "✅ 已啟用" if mod.status == ModStatus.ENABLED else "❌ 已停用"
            mod_base_name = mod.filename.removesuffix(".jar.disabled").removesuffix(".jar")

            size_val = getattr(mod, "file_size", 0)
            if size_val >= 1024 * 1024:
                display_size = f"{size_val / 1024 / 1024:.1f} MB"
            elif size_val >= 1024:
                display_size = f"{size_val / 1024:.1f} KB"
            else:
                display_size = f"{size_val} B"

            mtime_val = mod.file_mtime or 0.0
            display_mtime = datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M") if mtime_val else "未知"

            if mod_base_name in seen_mod_ids:
                continue
            seen_mod_ids.add(mod_base_name)

            values = (
                status_text,
                display_name,
                display_version,
                display_author,
                mod.loader_type,
                display_size,
                display_mtime,
                display_description,
            )
            projections.append(ModListRow(mod_base_name, tuple(str(value) for value in values), mod_base_name))

        self.controller.mod_session.replace_local_rows(projections)
        rows = {row.key: row for row in self.controller.mod_session.snapshot().local_rows}
        search_text = presenter.local_search_var.get()
        filter_status = presenter.local_filter_var.get()
        is_dark = isDarkTheme()
        primary_brush = QBrush(QColor(resolve_color(Colors.TEXT_PRIMARY, dark=is_dark)))
        muted_brush = QBrush(QColor(resolve_color(Colors.TEXT_MUTED, dark=is_dark)))
        tree.setUpdatesEnabled(False)
        try:
            with QSignalBlocker(tree):
                for key in tuple(self._local_items):
                    if key in rows:
                        continue
                    item = self._local_items.pop(key)
                    index = tree.indexOfTopLevelItem(item)
                    if index >= 0:
                        tree.takeTopLevelItem(index)

                for row in rows.values():
                    row_item = self._local_items.get(row.key)
                    if row_item is None:
                        row_item = QTreeWidgetItem(list(row.values))
                        row_item.setData(0, Qt.ItemDataRole.UserRole, row.data)
                        self._local_items[row.key] = row_item
                        tree.addTopLevelItem(row_item)
                    else:
                        for column, value in enumerate(row.values):
                            if row_item.text(column) != value:
                                row_item.setText(column, value)
                    row_item.setSelected(row.key in selected_mod_ids)
                    enabled = bool(row.values and "已啟用" in row.values[0])
                    status_matches = (
                        filter_status == "所有"
                        or (filter_status == "啟用" and enabled)
                        or (filter_status == "停用" and not enabled)
                    )
                    search_matches = not search_text or presenter.local_search_filter.matches(
                        (row.values[1],), search_text
                    )
                    row_item.setHidden(not status_matches or not search_matches)
                    brush = primary_brush if enabled else muted_brush
                    for column in range(len(row.values)):
                        if row_item.foreground(column) != brush:
                            row_item.setForeground(column, brush)
        finally:
            tree.setUpdatesEnabled(True)
        presenter.on_tree_selection_changed()

    def _build_online_browse_row(self, mod: Any) -> tuple[str, str, str, str, str, str]:
        """建立線上瀏覽列表單列顯示內容"""
        downloads = int(getattr(mod, "download_count", 0) or 0)
        return (
            str(getattr(mod, "name", "未知模組") or "未知模組"),
            str(getattr(mod, "author", "?") or "?"),
            f"{downloads:,}" if downloads > 0 else "N/A",
            str(getattr(mod, "source", "modrinth") or "modrinth").title(),
            self.format_online_environment_text(mod),
            format_single_line_text(getattr(mod, "description", "")),
        )

    def clear_online_results(self) -> None:
        """清空目前線上模組瀏覽結果"""
        self.controller.mod_session.clear_online_results()
        if self.controller.refresh_online_results_summary is not None:
            self.controller.scope.schedule(0, self.controller.refresh_online_results_summary)
        self.controller.scope.schedule(0, self.refresh_browse_list)

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

    def capture_selected_mod_ids(self) -> set[str]:
        """
        擷取目前選取列對應的 mod id（從 UserData 中取得）

        Returns:
            目前選取的模組識別碼集合
        """
        tree = self.controller.local_mod_list_presenter.local_tree
        if not tree:
            return set()

        selected_mod_ids = set()
        for item in tree.selectedItems():
            tags = item.data(0, Qt.ItemDataRole.UserRole)
            if tags:
                if isinstance(tags, str):
                    selected_mod_ids.add(tags)
                elif isinstance(tags, (tuple, list)) and len(tags) > 0:
                    selected_mod_ids.add(str(tags[0]))
        return selected_mod_ids


__all__ = ["ModManagementTreeSyncOps"]
