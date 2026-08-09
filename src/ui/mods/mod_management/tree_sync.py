"""本地與線上 Tree 同步"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from ....models import ModStatus
from .constants import logger
from .online_mod_queue import ModManagementRuntimeBase


class ModManagementTreeSyncMixin(ModManagementRuntimeBase):
    """維護本地與線上模組列表的同步與刷新"""

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
    def _format_online_environment_text(mod: Any) -> str:
        """格式化線上模組的支援環境"""
        server_side = str(getattr(mod, "server_side", "") or "").strip()
        client_side = str(getattr(mod, "client_side", "") or "").strip()
        if client_side and server_side:
            return "兼容（客戶端/伺服器）"
        if client_side:
            return "僅客戶端"
        if server_side:
            return "僅伺服器"
        return "未知"

    def refresh_browse_list(self) -> None:
        """重新整理線上模組列表"""
        self._refresh_online_results_summary()
        tree = getattr(self, "browse_tree", None)
        if not tree:
            return

        logger.debug(f"重新整理線上模組列表: result_count={len(self.online_mods)}")

        mod_order: list[str] = []
        mod_rows: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        seen_row_keys: set[str] = set()

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
            seen_row_keys.add(row_key)

        tree.clear()

        items = []
        for row_key in mod_order:
            values, tags = mod_rows[row_key]
            item = QTreeWidgetItem([str(v) for v in values])
            item.setData(0, Qt.ItemDataRole.UserRole, tags)
            items.append(item)

        if items:
            tree.addTopLevelItems(items)

    def refresh_local_list(self) -> None:
        """重新整理本地模組列表"""
        tree = getattr(self, "local_tree", None)
        if not tree:
            return

        selected_mod_ids = self._capture_selected_mod_ids()

        search_text = ""
        if hasattr(self, "local_search_var"):
            search_var = self.local_search_var
            search_text = (
                search_var.get()
                if hasattr(search_var, "get")
                else (search_var.text() if hasattr(search_var, "text") else str(search_var))
            )

        search_filter = getattr(self, "local_search_filter", None)

        filter_status = "所有"
        if hasattr(self, "local_filter_var"):
            filter_var = self.local_filter_var
            filter_status = (
                filter_var.get()
                if hasattr(filter_var, "get")
                else (filter_var.text() if hasattr(filter_var, "text") else str(filter_var))
            )

        version_pattern = getattr(self, "VERSION_PATTERN", None)

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

            enhanced = getattr(self, "enhanced_mods_cache", {}).get(mod.filename)
            parsed_version = "未知"
            if version_pattern:
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

            raw_desc = self._get_enhanced_attr(enhanced, "description", mod.description or "")
            if hasattr(self, "_format_single_line_text"):
                display_description = self._format_single_line_text(raw_desc)
            else:
                display_description = str(raw_desc)

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
            mod_order.append(mod_base_name)
            mod_rows[mod_base_name] = (values, mod_base_name)

        tree.clear()

        items = []
        for mod_id in mod_order:
            values, tags = mod_rows[mod_id]
            item = QTreeWidgetItem([str(v) for v in values])
            item.setData(0, Qt.ItemDataRole.UserRole, tags)
            if mod_id in selected_mod_ids:
                item.setSelected(True)
            items.append(item)

        if items:
            tree.addTopLevelItems(items)

        if hasattr(self, "on_tree_selection_changed"):
            self.on_tree_selection_changed()

    def _build_online_browse_row(self, mod: Any) -> tuple[str, str, str, str, str, str]:
        """建立線上瀏覽列表單列顯示內容"""
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
        """清空目前線上模組瀏覽結果"""
        self.online_mods = []
        self._online_mod_index = {}
        self.ui_queue.put(self._refresh_online_results_summary)
        self.ui_queue.put(self.refresh_browse_list)

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

    def _capture_selected_mod_ids(self) -> set[str]:
        """擷取目前選取列對應的 mod id（從 UserData 中取得）"""
        tree = getattr(self, "local_tree", None)
        if not tree:
            return set()

        selected_mod_ids = set()
        for item in tree.selectedItems():
            tags = item.data(0, Qt.ItemDataRole.UserRole)
            if tags and isinstance(tags, tuple) and len(tags) > 0:
                selected_mod_ids.add(str(tags[0]))
        return selected_mod_ids


__all__ = ["ModManagementTreeSyncMixin"]
