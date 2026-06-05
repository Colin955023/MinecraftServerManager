"""線上瀏覽與安裝佇列流程。"""

from __future__ import annotations

# 直接內嵌原 runtime_typing 內容，避免循環依賴
import contextlib
import queue
import re
import traceback
from typing import Any

from ...core import AppException
from ...utils import (
    Colors,
    FontSize,
    Sizes,
    Spacing,
    UIUtils,
)
from ...utils.ui_support import qt_widgets as qt
from .. import (
    DialogUtils,
    FontManager,
    TaskUtils,
    TreeUtils,
    analyze_mod_version_compatibility,
    get_mod_versions,
    resolve_modrinth_project_names,
    search_mods_online,
)
from .constants import SUPPORTED_ONLINE_MOD_LOADERS, logger
from .models import OnlineBrowseRequest, PendingOnlineInstall


class ModManagementRuntimeBase:
    """為拆分後的 mixin 提供共同宿主屬性型別。"""

    parent: Any
    current_server: Any | None
    mod_manager: Any | None
    notebook: Any | None
    browse_tree: qt.Treeview | None
    browse_filter_label: Any | None
    browse_results_label: Any | None
    browse_sort_var: Any
    browse_sort_options: dict[str, str]
    local_tree: qt.Treeview | None
    local_mods: list[Any]
    online_mods: list[Any]
    pending_online_installs: list[PendingOnlineInstall]
    ui_queue: queue.Queue[Any]
    enhanced_mods_cache: dict[str, Any]
    VERSION_PATTERN: re.Pattern[str]
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
        """讓共同宿主 mixin 的交叉方法在型別檢查時保持可見。"""
        raise AttributeError(_name)


class ModManagementQueueMixin(ModManagementRuntimeBase):
    """封裝線上瀏覽、搜尋與安裝佇列互動流程。"""

    def _get_current_modrinth_context(self) -> tuple[str | None, str | None, str | None]:
        """依目前選取伺服器取得 Minecraft、loader 與 loader 版本資訊。"""
        if not self.current_server:
            return (None, None, None)
        minecraft_version = str(getattr(self.current_server, "minecraft_version", "") or "").strip() or None
        loader_type = str(getattr(self.current_server, "loader_type", "") or "").strip() or None
        loader_version = str(getattr(self.current_server, "loader_version", "") or "").strip() or None
        return (minecraft_version, loader_type, loader_version)

    def _get_current_modrinth_filters(self) -> tuple[str | None, str | None]:
        """依目前選取伺服器取得 Minecraft 版本與 loader 過濾條件。"""
        minecraft_version, loader_type, _ = self._get_current_modrinth_context()
        return (minecraft_version, loader_type)

    def _get_online_filter_hint_text(self) -> str:
        """建立線上模組瀏覽/搜尋提示文字。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.current_server:
            return "請先選擇伺服器並輸入關鍵字後搜尋；僅支援 Fabric / Forge / Quilt / NeoForge。"
        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)
        hint = "條件：" + " / ".join(info_parts)
        if not loader_type or loader_type.lower() not in SUPPORTED_ONLINE_MOD_LOADERS:
            return hint + "｜僅支援 Fabric / Forge / Quilt / NeoForge"
        return hint + "｜請輸入關鍵字後搜尋"

    def _get_online_version_dialog_hint_text(self) -> str:
        """建立版本選擇視窗的伺服器條件摘要。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.current_server:
            return "會依目前伺服器條件自動分析版本相容性。"
        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)
        return "相容性條件：" + " / ".join(info_parts)

    def _refresh_online_filter_hint(self) -> None:
        """更新線上模組搜尋提示。"""
        if self.browse_filter_label:
            self.browse_filter_label.configure(text=self._get_online_filter_hint_text())

    def _get_online_sort_label(self) -> str:
        """取得目前線上瀏覽使用的排序顯示文字。"""
        if not hasattr(self, "browse_sort_var"):
            return "相關性"
        return str(self.browse_sort_var.get() or "相關性").strip() or "相關性"

    @staticmethod
    def _format_single_line_text(value: Any) -> str:
        """將多行或多空白文字正規化為單行。"""
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _format_online_result_description(self, mod: Any) -> str:
        """格式化瀏覽列表描述欄位。"""
        return self._format_single_line_text(getattr(mod, "description", ""))

    def _get_selected_online_mod_context(self) -> tuple[bool, str, Any | None]:
        """取得目前線上模組選取狀態、project_id 與模組物件。"""
        if not self.browse_tree:
            return (False, "", None)
        selection = self.browse_tree.selection()
        if not selection:
            return (False, "", None)
        item = selection[0]
        tags = self.browse_tree.item(item, "tags")
        project_id = str(tags[0]) if tags else ""
        mod = self._online_mod_index.get(project_id)
        if mod is None:
            mod = self._online_mod_by_row_key.get(str(item))
            if mod is not None and not project_id:
                project_id = str(getattr(mod, "project_id", "") or "").strip()
        return (True, project_id, mod)

    def _build_online_results_summary_text(self) -> str:
        """建立瀏覽/搜尋結果摘要，說明目前條件與結果數量。"""
        query = self._get_online_query_text()
        mode_text = "請輸入關鍵字搜尋" if not query else f"搜尋 {query}"
        sort_text = self._get_online_sort_label()
        result_count = len(self.online_mods)
        return f"{mode_text}｜{result_count} 筆｜排序 {sort_text}"

    def _refresh_online_results_summary(self) -> None:
        """更新瀏覽結果摘要列。"""
        if self.browse_results_label:
            self.browse_results_label.configure(text=self._build_online_results_summary_text())

    def _get_online_query_text(self) -> str:
        """取得目前線上模組輸入框文字。"""
        if not hasattr(self, "search_var"):
            return ""
        query = self.search_var.get() or ""
        search_filter = getattr(self, "online_search_filter", None)
        if search_filter is not None:
            return search_filter.normalize(query)
        return str(query).strip()

    def _build_online_browse_request(self) -> tuple[OnlineBrowseRequest | None, str | None]:
        """建立目前的線上瀏覽/搜尋請求。"""
        minecraft_version, _ = self._get_current_modrinth_filters()
        loader_type, warning_message = self._get_supported_online_loader()
        if warning_message or not loader_type:
            return (None, warning_message)
        query = self._get_online_query_text()
        if not query:
            return (None, "請先輸入關鍵字再搜尋模組。")
        sort_by = self.browse_sort_options.get(self.browse_sort_var.get(), "relevance")
        return (
            OnlineBrowseRequest(
                query=query, minecraft_version=minecraft_version, loader_type=loader_type, sort_by=sort_by
            ),
            None,
        )

    def _is_browse_tab_active(self) -> bool:
        """判斷目前是否正在顯示線上瀏覽頁。"""
        if not self.notebook:
            return False
        try:
            return self.notebook.index(self.notebook.select()) == 1
        except Exception:
            return False

    def _load_online_mods(self, *, force: bool = False, show_warning: bool = True) -> None:
        """依目前條件載入線上模組（需輸入關鍵字）。"""
        request, warning_message = self._build_online_browse_request()
        if request is None:
            if show_warning:
                UIUtils.show_warning("目前不支援", warning_message, self.parent)
            self._clear_online_mods()
            return
        if not force and request == self._last_online_request and self.online_mods:
            return

        def search_task() -> None:
            try:
                filter_hint = self._get_online_filter_hint_text()
                self.update_status_safe(f"正在搜尋 Modrinth 模組... {filter_hint}")
                mods = search_mods_online(
                    request.query,
                    minecraft_version=request.minecraft_version,
                    loader=request.loader_type,
                    sort_by=request.sort_by,
                )
                self.online_mods = mods
                self._online_mod_index = {mod.project_id: mod for mod in mods if getattr(mod, "project_id", "")}
                online_mod_by_row_key: dict[str, Any] = {}
                for mod in mods:
                    row_key = self._build_online_browse_key(mod)
                    if row_key:
                        online_mod_by_row_key[row_key] = mod
                self._online_mod_by_row_key = online_mod_by_row_key
                self._last_online_request = request
                self.ui_queue.put(self.refresh_browse_list)
                self.update_status_safe(f"找到 {len(mods)} 個線上模組")
            except AppException as e:
                logger.warning(f"搜尋線上模組失敗（可恢復）: {e}")
                self.update_status_safe(f"搜尋線上模組失敗: {e}")
            except Exception:
                logger.error("搜尋線上模組失敗: 未知錯誤\n" + traceback.format_exc())
                self.update_status_safe("搜尋線上模組失敗：內部錯誤")

        TaskUtils.run_async(search_task)

    def on_online_browse_filters_changed(self, _value: str) -> None:
        """線上瀏覽排序變更時立即刷新清單。

        Args:
            _value: 下拉選單回傳的目前值。
        """
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()
        self._load_online_mods(force=True, show_warning=False)

    def search_online_mods(self, _event=None) -> None:
        """載入 Modrinth 線上模組並觸發搜尋。

        Args:
            _event: 事件繫結傳入的事件物件，未使用。
        """
        self._load_online_mods(force=True, show_warning=True)

    def show_browse_context_menu(self, event) -> None:
        """顯示線上模組右鍵選單。

        Args:
            event: 觸發選單的滑鼠事件。
        """
        has_selection, _, _ = self._get_selected_online_mod_context()
        if not has_selection:
            return
        menu = qt.PopupMenu(self.parent, tearoff=0, font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        menu.add_command(label="⬇️ 安裝模組", command=self.install_online_mod)
        menu.add_separator()
        menu.add_command(label="📋 複製模組資訊", command=self.copy_online_mod_info)
        menu.add_command(label="🌐 開啟模組頁面", command=self.open_mod_webpage)
        try:
            menu.popup_at(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def install_online_mod(self, _event=None) -> None:
        """取得模組版本列表並讓使用者選擇要安裝的版本。

        Args:
            _event: 事件繫結傳入的事件物件，未使用。
        """
        manager = self.mod_manager
        if not self.current_server or not manager:
            UIUtils.show_warning("警告", "請先選擇伺服器後再安裝模組", self.parent)
            return
        has_selection, _, selected_mod = self._get_selected_online_mod_context()
        if not has_selection:
            UIUtils.show_warning("警告", "請先從線上列表選取模組", self.parent)
            return
        if not selected_mod:
            UIUtils.show_error("錯誤", "找不到選取的線上模組資料", self.parent)
            return
        minecraft_version, _, loader_version = self._get_current_modrinth_context()
        loader_type, warning_message = self._get_supported_online_loader()
        if warning_message:
            UIUtils.show_warning("目前不支援", warning_message, self.parent)
            return

        def load_versions_task() -> None:
            try:
                self.update_status_safe(f"正在讀取 {selected_mod.name} 的版本列表...")
                versions = get_mod_versions(selected_mod.project_id, minecraft_version, loader_type)
                if not versions:
                    versions = get_mod_versions(selected_mod.project_id)
                installed_mods = manager.get_mod_list()
                dependency_project_ids = {
                    str(dependency.get("project_id", "") or "").strip()
                    for version in versions
                    for dependency in getattr(version, "dependencies", []) or []
                    if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
                }
                dependency_names = resolve_modrinth_project_names(dependency_project_ids)
                version_reports = [
                    analyze_mod_version_compatibility(
                        version,
                        project_id=selected_mod.project_id,
                        project_name=selected_mod.name,
                        minecraft_version=minecraft_version,
                        loader=loader_type,
                        loader_version=loader_version,
                        installed_mods=installed_mods,
                        dependency_names=dependency_names,
                    )
                    for version in versions
                ]
                versions, version_reports = self._sort_online_versions_for_server(versions, version_reports)

                def open_dialog() -> None:
                    if not versions:
                        UIUtils.show_warning("找不到版本", f"{selected_mod.name} 目前查無可下載版本", self.parent)
                        return
                    self._show_version_install_dialog(selected_mod, versions, version_reports)

                self.ui_queue.put(open_dialog)
                self.update_status_safe(f"已載入 {selected_mod.name} 的 {len(versions)} 個版本")
            except Exception as e:
                logger.error(f"取得模組版本失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"取得模組版本失敗: {e}")

        TaskUtils.run_async(load_versions_task)

    def _show_version_install_dialog(
        self, mod: Any, versions: list[Any], version_reports: list[Any] | None = None
    ) -> None:
        """顯示版本選擇對話框。"""
        dialog = DialogUtils.create_toplevel_dialog(
            self.parent,
            f"安裝模組 - {mod.name}",
            width=Sizes.DIALOG_LARGE_WIDTH,
            height=Sizes.DIALOG_LARGE_HEIGHT,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=250,
            min_width=750,
            min_height=645,
        )
        main_frame = qt.Frame(dialog)
        main_frame.attach(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)
        title = qt.Label(
            main_frame,
            text=f"選擇要安裝的版本：{mod.name}",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title.attach(anchor="w", padx=Spacing.MEDIUM, pady=(Spacing.MEDIUM, Spacing.SMALL_PLUS))
        filter_label = qt.Label(
            main_frame,
            text=self._get_online_version_dialog_hint_text(),
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=Sizes.ONLINE_VERSION_HINT_WRAP_LENGTH,
        )
        filter_label.attach(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
        tree_container = qt.Frame(main_frame)
        tree_container.attach(fill="both", expand=True, padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))
        columns = ("version", "type", "minecraft", "loader", "status", "date")
        version_tree = qt.Treeview(tree_container, columns=columns, show="headings", height=Spacing.MEDIUM)
        column_config = {
            "version": ("版本", 75),
            "type": ("類型", 35),
            "minecraft": ("Minecraft", 75),
            "loader": ("Loader", 60),
            "status": ("狀態", 70),
            "date": ("發布時間", 85),
        }
        for col, (text, width) in column_config.items():
            version_tree.heading(col, text=text, anchor="w")
            is_stretch = col == "date"
            version_tree.column(col, width=width, minwidth=width if is_stretch else 30, anchor="w", stretch=is_stretch)
        TreeUtils.bind_treeview_header_auto_fit(
            version_tree,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"date"},
        )
        version_scroll = qt.Scrollbar(tree_container, orient="vertical", command=version_tree.yview)
        version_tree.configure(yscrollcommand=version_scroll.set)
        version_tree.attach_matrix(row=0, column=0, sticky="nsew")
        version_scroll.attach_matrix(row=0, column=1, sticky="ns")
        tree_container.set_grid_row_stretch(0, weight=1)
        tree_container.set_grid_column_stretch(0, weight=1)
        for index, version in enumerate(versions):
            published = str(getattr(version, "date_published", "") or "")
            report = None
            if version_reports and index < len(version_reports):
                report = version_reports[index]
            status_text = self._get_online_version_status_text(report)
            v_type = getattr(version, "version_type", "") or ""
            type_display = "正式版" if v_type == "release" else ("測試版" if "beta" in v_type else v_type.capitalize())
            version_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    getattr(version, "display_name", "未知版本"),
                    type_display,
                    ", ".join(getattr(version, "game_versions", []) or []) or "-",
                    ", ".join(getattr(version, "loaders", []) or []) or "-",
                    status_text,
                    published.replace("T", " ").replace("Z", "")[:16] if published else "-",
                ),
            )
        if versions:
            version_tree.selection_set("0")
        TreeUtils.refresh_treeview_alternating_rows(version_tree)
        summary_label = qt.Label(
            main_frame, text="版本分析", font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold")
        )
        summary_label.attach(anchor="w", padx=Spacing.MEDIUM, pady=(0, Spacing.TINY))
        summary_box = self._create_review_summary_box(main_frame, height=Sizes.SERVER_TREE_COL_LOADER)
        button_frame = qt.Frame(main_frame, fg_color="transparent")
        button_frame.attach(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
        install_button = qt.Button(
            button_frame,
            text="➕ 加入安裝清單",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=lambda: self._install_online_version(mod, versions, version_tree, dialog, version_reports),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        install_button.attach(side="left")
        open_button = qt.Button(
            button_frame,
            text="🧺 查看清單",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=self.show_online_install_queue,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        open_button.attach(side="left", padx=(Spacing.SMALL_PLUS, 0))
        project_page_url = self._resolve_online_mod_project_page_url(mod)
        project_page_button = qt.Button(
            button_frame,
            text="🌐 專案頁面",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=lambda: self._open_project_page(project_page_url, dialog),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
            state="normal" if project_page_url else "disabled",
        )
        project_page_button.attach(side="left", padx=(Spacing.SMALL_PLUS, 0))
        close_button = qt.Button(
            button_frame,
            text="關閉",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_SECONDARY,
            hover_color=Colors.BUTTON_SECONDARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=dialog.destroy,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        close_button.attach(side="right")

        def refresh_version_report(_event=None) -> None:
            selection = version_tree.selection()
            if not selection:
                return
            selected_index = int(selection[0])
            selected_version = versions[selected_index]
            report = None
            if version_reports and selected_index < len(version_reports):
                report = version_reports[selected_index]
            summary_box.setReadOnly(False)
            summary_box.delete("1.0", "end")
            summary_box.insert("1.0", self._format_online_version_report(selected_version, report))
            summary_box.setReadOnly(True)
            install_button.configure(
                state="normal" if report is None or getattr(report, "compatible", True) else "disabled"
            )

        version_tree.connect_event("selection_changed", refresh_version_report)
        refresh_version_report()
        DialogUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=750,
            min_height=645,
            parent=self.parent,
            preserve_current_size=False,
        )

    def copy_online_mod_info(self) -> None:
        """複製線上模組資訊。"""
        _, _, mod = self._get_selected_online_mod_context()
        if not mod:
            return
        downloads = int(getattr(mod, "download_count", 0) or 0)
        info = (
            f"模組名稱: {getattr(mod, 'name', '未知模組') or '未知模組'}\n"
            f"作者: {getattr(mod, 'author', '?') or '?'}\n"
            f"下載數: {f'{downloads:,}' if downloads > 0 else 'N/A'}\n"
            f"平台: {str(getattr(mod, 'source', 'modrinth') or 'modrinth').title()}\n"
            f"支援環境: {self._format_online_environment_text(mod)}\n"
            f"頁面: {getattr(mod, 'url', '')}"
        )
        try:
            app = qt.ensure_app()
            app.clipboard().setText(info)
            with contextlib.suppress(Exception):
                app.processEvents()
        except Exception as e:
            logger.error(f"複製線上模組資訊失敗: {e}")
            UIUtils.show_error("複製失敗", f"無法將模組資訊複製到剪貼簿：{e}", self.parent)
            return
        self.update_status("線上模組資訊已複製到剪貼簿")

    def open_mod_webpage(self) -> None:
        """開啟選取模組的 Modrinth 頁面。"""
        _, _, mod = self._get_selected_online_mod_context()
        if not mod:
            return
        url = self._resolve_online_mod_project_page_url(mod)
        if url:
            UIUtils.open_external(url)


__all__ = ["ModManagementQueueMixin"]
