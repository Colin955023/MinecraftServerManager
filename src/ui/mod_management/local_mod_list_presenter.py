"""本地模組列表 Presenter。"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from ...core import ModStatus
from ...utils import Colors, FontSize, Sizes, Spacing, UIUtils, get_shared_manager
from ...utils.ui_support import qt_widgets as qt
from ..custom_dropdown import CustomDropdown
from ..font_manager import FontManager
from ..mod_search_service.modrinth_service import enhance_local_mod
from ..task_utils import TaskUtils
from ..tree_utils import TreeUtils
from .constants import MOD_TOOL_BUTTON_STYLE, logger
from .presenter_delegate_mixin import PresenterDelegateMixin


class LocalModListPresenter(PresenterDelegateMixin):
    """封裝本地模組列表的 UI 建立、篩選、選取與批次操作。"""

    def __init__(self, frame: Any):
        super().__init__(frame)
        self.all_selected: bool = False

    @staticmethod
    def _get_current_server_path_key(current_server: Any | None) -> str | None:
        server_path = str(getattr(current_server, "path", "") or "").strip()
        if not server_path:
            return None
        try:
            return str(Path(server_path).resolve())
        except Exception:
            return server_path

    @staticmethod
    def _build_mods_dir_signature(mods_dir: Path | None) -> tuple[tuple[str, int, int], ...] | None:
        if mods_dir is None or not mods_dir.exists():
            return ()
        try:
            signature: list[tuple[str, int, int]] = []
            for entry in mods_dir.iterdir():
                if not entry.is_file():
                    continue
                try:
                    stat_result = entry.stat()
                except OSError:
                    continue
                signature.append((entry.name, int(stat_result.st_mtime_ns), int(stat_result.st_size)))
            return tuple(sorted(signature))
        except OSError:
            return None

    def _is_local_mods_scope_current(self, request_token: int, server_path_key: str | None) -> bool:
        current_token = int(getattr(self, "_local_mods_load_token", 0))
        if request_token != current_token:
            return False
        return self._get_current_server_path_key(getattr(self, "current_server", None)) == server_path_key

    def render_local_mods(self) -> None:
        """重新渲染目前本地模組列表。"""
        self.refresh_local_list()

    def handle_selection(self, _event=None) -> None:
        """
        同步本地模組列表的目前選取狀態。

        Args:
            _event: 觸發選取變更的事件物件（可選）。目前未使用，但保留以符合事件處理器簽名。
        """
        self.on_tree_selection_changed(_event)

    def batch_toggle(self) -> None:
        """批量切換目前選取模組的啟用狀態。"""
        self.batch_toggle_selected()

    def create_local_toolbar(self) -> None:
        """建立本地模組工具列。"""
        toolbar_frame = qt.Frame(self.local_tab)
        toolbar_frame.attach(fill="x", padx=Spacing.MEDIUM, pady=Spacing.MEDIUM)
        left_frame = qt.Frame(toolbar_frame, fg_color="transparent")
        left_frame.attach(side="left", padx=Spacing.SMALL)
        import_btn = qt.Button(
            left_frame,
            text="📁 匯入模組",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.import_mod_file,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        import_btn.attach(side="left", padx=(0, 12))
        refresh_mod_list_btn = qt.Button(
            left_frame,
            text="🔄 重新整理",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.refresh_mod_list_force,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        refresh_mod_list_btn.attach(side="left", padx=(0, 12))
        update_btn = qt.Button(
            left_frame,
            text="🔄 檢查更新",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.check_local_mod_updates,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        update_btn.attach(side="left", padx=(0, 12))
        self.select_all_btn = qt.Button(
            left_frame,
            text="☑️ 全選",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.toggle_select_all,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.select_all_btn.attach(side="left", padx=(0, 12))
        self.batch_toggle_btn = qt.Button(
            left_frame,
            text="🔄 批量切換",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.batch_toggle_selected,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.batch_toggle_btn.attach(side="left", padx=(0, 12))
        folder_btn = qt.Button(
            left_frame,
            text="📂 開啟資料夾",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.open_mods_folder,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        folder_btn.attach(side="left")
        right_frame = qt.Frame(toolbar_frame, fg_color="transparent")
        right_frame.attach(side="right", padx=Spacing.LARGE_MINUS)
        search_frame = qt.Frame(right_frame, fg_color="transparent")
        search_frame.attach(side="left", padx=(0, Spacing.LARGE_MINUS))
        self.local_search_var = qt.TextState()
        self.local_search_filter = qt.SearchFilter()
        search_entry = qt.SearchEntry(
            search_frame,
            textvariable=self.local_search_var,
            filter_logic=self.local_search_filter,
            placeholder_text="搜尋本地模組",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            width=Sizes.DROPDOWN_COMPACT_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        search_entry.attach(side="left")
        self.local_search_var.trace("w", self.filter_local_mods)
        self.local_filter_var = qt.TextState(value="所有")
        filter_combo = CustomDropdown(
            right_frame,
            variable=self.local_filter_var,
            values=["所有", "啟用", "停用"],
            command=self.on_filter_changed,
            width=Sizes.DROPDOWN_FILTER_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        filter_combo.attach(side="left")

    def on_filter_changed(self, _value: str) -> None:
        """
        本地模組篩選條件變更時重新過濾列表。

        Args:
            _value: 下拉選單回傳的目前值。
        """
        self.filter_local_mods()

    def refresh_mod_list_force(self) -> None:
        """強制重新掃描本地模組並重繪列表。"""
        if self.mod_manager:
            manager = self.mod_manager

            def load_thread():
                try:
                    self.update_status_safe("正在強制重新掃描本地模組...")
                    mods = manager.scan_mods()
                    self.local_mods = mods
                    self.enhanced_mods_cache = {}
                    self.enhance_local_mods()
                    self.update_status_safe(f"找到 {len(mods)} 個本地模組 (已重新整理)")
                except Exception as e:
                    logger.bind(component="").error(
                        f"強制掃描失敗: {e}\n{traceback.format_exc()}", "ModManagementFrame"
                    )
                    self.update_status_safe(f"強制掃描失敗: {e}")

            TaskUtils.run_async(load_thread)

    def create_local_mod_list(self) -> None:
        """建立本地模組列表。"""
        list_frame = qt.Frame(self.local_tab)
        list_frame.attach(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=(0, Spacing.SMALL_PLUS))
        export_btn = qt.Button(
            list_frame,
            text="匯出模組列表",
            font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            **MOD_TOOL_BUTTON_STYLE,
            command=self.export_mod_list_dialog,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT_EXPORT,
        )
        export_btn.attach(anchor="ne", pady=(Spacing.SMALL_PLUS, Spacing.TINY), padx=Spacing.SMALL_PLUS)
        tree_container = qt.Frame(list_frame)
        tree_container.attach(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=(0, Spacing.SMALL_PLUS))
        columns = ("status", "name", "version", "author", "loader", "size", "mtime", "description")
        self.local_tree = qt.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=Sizes.TREEVIEW_VISIBLE_ROWS,
            selectmode="extended",
        )
        column_config = {
            "status": ("狀態", 40),
            "name": ("模組名稱", 100),
            "version": ("版本", 50),
            "author": ("作者", 60),
            "loader": ("載入器", 40),
            "size": ("檔案大小", 50),
            "mtime": ("修改時間", 60),
            "description": ("描述", 230),
        }
        for col, (text, width) in column_config.items():
            self.local_tree.heading(col, text=text, anchor="w")
            is_stretch = col == "description"
            self.local_tree.column(col, width=width, minwidth=width if is_stretch else 25, stretch=is_stretch)
        v_scrollbar = qt.Scrollbar(tree_container, orient="vertical", command=self.local_tree.yview)
        h_scrollbar = qt.Scrollbar(tree_container, orient="horizontal", command=self.local_tree.xview)
        self.local_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.local_v_scrollbar = v_scrollbar
        self.local_h_scrollbar = h_scrollbar
        self.local_tree.attach_matrix(row=0, column=0, sticky="nsew")
        v_scrollbar.attach_matrix(row=0, column=1, sticky="ns")
        h_scrollbar.attach_matrix(row=1, column=0, sticky="ew")
        is_dark = qt.is_dark_color_scheme()
        bg_odd, bg_even = self._get_local_row_palette(is_dark)
        fg = Colors.TEXT_ON_DARK if is_dark else Colors.TEXT_HEADING[0]
        self.local_tree.tag_configure("odd", background=bg_odd, foreground=fg)
        self.local_tree.tag_configure("even", background=bg_even, foreground=fg)
        tree_container.set_grid_row_stretch(0, weight=1)
        tree_container.set_grid_column_stretch(0, weight=1)
        TreeUtils.bind_treeview_header_auto_fit(
            self.local_tree,
            on_row_double_click=self.toggle_local_mod,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"description"},
        )
        self.local_tree.connect_event("mouse_right_press", self.show_local_context_menu)
        self.local_tree.connect_event("selection_changed", self.on_tree_selection_changed)

    def apply_local_tree_theme(self) -> None:
        """重新套用本地模組清單的主題色與交錯列文字色。"""
        if not self.local_tree:
            return
        if hasattr(self.local_tree, "apply_theme_style"):
            self.local_tree.apply_theme_style()
        is_dark = qt.is_dark_color_scheme()
        bg_odd, bg_even = self._get_local_row_palette(is_dark)
        fg = Colors.TEXT_ON_DARK if is_dark else Colors.TEXT_HEADING[0]
        self.local_tree.tag_configure("odd", background=bg_odd, foreground=fg)
        self.local_tree.tag_configure("even", background=bg_even, foreground=fg)

    def load_local_mods(self) -> None:
        """載入本地模組，並同步清空增強 cache，確保顯示一致。"""
        if not self.mod_manager:
            return
        manager = self.mod_manager
        request_token = int(getattr(self, "_local_mods_load_token", 0)) + 1
        self._local_mods_load_token = request_token
        current_server = getattr(self, "current_server", None)
        server_path_key = self._get_current_server_path_key(current_server)
        mods_dir = Path(server_path_key) / "mods" if server_path_key else None
        mods_dir_key = str(mods_dir.resolve()) if mods_dir else ""
        mods_dir_signature = self._build_mods_dir_signature(mods_dir)
        try:
            mods_dir_mtime = mods_dir.stat().st_mtime if mods_dir and mods_dir.exists() else None
        except Exception:
            mods_dir_mtime = None
        if (
            mods_dir_key
            and mods_dir_key == getattr(self, "_last_mods_dir", None)
            and (mods_dir_signature is not None)
            and (mods_dir_signature == getattr(self, "_last_mods_dir_signature", None))
        ):
            self.update_status_safe(f"找到 {len(self.local_mods)} 個本地模組")
            self.ui_queue.put(self.refresh_local_list)
            return

        def load_thread():
            try:
                self.update_status_safe("正在掃描本地模組...")
                mods = list(manager.scan_mods())
                dedup: dict[str, Any] = {}
                for mod in mods:
                    base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                    existing = dedup.get(base_name)
                    if existing is None or mod.status == ModStatus.ENABLED:
                        dedup[base_name] = mod
                mods = list(dedup.values())
                total = len(mods)
                new_local_mods: list[Any] = []
                last_percent = -1
                for idx, mod in enumerate(mods):
                    if not self._is_local_mods_scope_current(request_token, server_path_key):
                        logger.debug("略過過期的本地模組掃描結果", "ModManagementFrame")
                        return
                    try:
                        mod._cached_mtime = Path(mod.file_path).stat().st_mtime
                    except Exception:
                        mod._cached_mtime = None
                    new_local_mods.append(mod)
                    percent = (idx + 1) / total * 100 if total else 0
                    rounded_percent = int(percent)
                    if rounded_percent != last_percent:
                        last_percent = rounded_percent
                        self.update_progress_safe(percent)
                current_signature = self._build_mods_dir_signature(mods_dir)
                if current_signature is None:
                    current_signature = mods_dir_signature
                if not self._is_local_mods_scope_current(request_token, server_path_key):
                    logger.debug("略過過期的本地模組掃描結果", "ModManagementFrame")
                    return
                if current_signature != mods_dir_signature:
                    logger.debug("本地模組目錄在掃描期間已變更，略過過期結果", "ModManagementFrame")
                    return
                self.local_mods = new_local_mods
                self.enhanced_mods_cache = {}
                self._last_mods_dir = mods_dir_key
                try:
                    self._last_mods_dir_mtime = mods_dir.stat().st_mtime if mods_dir and mods_dir.exists() else None
                except Exception:
                    self._last_mods_dir_mtime = mods_dir_mtime
                self._last_mods_dir_signature = current_signature
                self.enhance_local_mods(request_token=request_token, server_path_key=server_path_key)
                self.update_status_safe(f"找到 {len(mods)} 個本地模組")
            except Exception as e:
                logger.error(f"掃描失敗: {e}\n{traceback.format_exc()}")
                self.update_progress_safe(0)
                self.update_status_safe(f"掃描失敗: {e}")

        TaskUtils.run_async(load_thread)

    def enhance_local_mods(self, request_token: int | None = None, server_path_key: str | None = None) -> None:
        """查詢本地模組增強資訊，查詢完成後刷新列表。

        Args:
            request_token: 用來比對目前是否仍為同一輪載入的 token。
            server_path_key: 目前伺服器路徑的正規化快照，用來避免伺服器切換後寫回舊結果。
        """

        if request_token is None:
            request_token = int(getattr(self, "_local_mods_load_token", 0))
        if server_path_key is None:
            server_path_key = self._get_current_server_path_key(getattr(self, "current_server", None))
        if not self._is_local_mods_scope_current(request_token, server_path_key):
            return

        def enhance_single(mod):
            try:
                if not self._is_local_mods_scope_current(request_token, server_path_key):
                    return
                if mod.filename in self.enhanced_mods_cache:
                    return
                enhanced = enhance_local_mod(
                    mod.filename,
                    platform_id=getattr(mod, "platform_id", ""),
                    platform_slug=getattr(mod, "platform_slug", ""),
                    local_name=getattr(mod, "name", ""),
                )
                if enhanced:
                    if not self._is_local_mods_scope_current(request_token, server_path_key):
                        return
                    resolved_project_id = str(getattr(enhanced, "project_id", "") or "").strip()
                    resolved_slug = str(getattr(enhanced, "slug", "") or "").strip()
                    if resolved_project_id:
                        mod.platform_id = resolved_project_id
                    if resolved_slug and hasattr(mod, "platform_slug"):
                        mod.platform_slug = resolved_slug
                    self.enhanced_mods_cache[mod.filename] = enhanced
                    self._cache_local_provider_metadata(mod, enhanced)
                    time.sleep(0.05)
            except Exception as e:
                logger.bind(component="").error(
                    f"模組 {mod.filename} 資訊失敗: {e}\n{traceback.format_exc()}", "ModManagementFrame"
                )

        def enhance_thread():
            if not self._is_local_mods_scope_current(request_token, server_path_key):
                return
            futures = [get_shared_manager().run(enhance_single, mod) for mod in list(self.local_mods)]
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    logger.debug(f"模組增強背景工作失敗: {e}", "ModManagementFrame")
            if not self._is_local_mods_scope_current(request_token, server_path_key):
                return
            self.ui_queue.put(self.refresh_local_list)

        TaskUtils.run_async(enhance_thread)

    def _set_bulk_controls_enabled(self, enabled: bool) -> None:
        """設定批量操作控制元件的啟用/停用狀態。"""
        state = "normal" if enabled else "disabled"
        try:
            if hasattr(self, "select_all_btn") and self.select_all_btn:
                self.select_all_btn.configure(state=state)
        except Exception as e:
            logger.debug(f"設定全選按鈕狀態失敗: {e}", "ModManagement")
        try:
            if hasattr(self, "batch_toggle_btn") and self.batch_toggle_btn:
                self.batch_toggle_btn.configure(state=state)
        except Exception as e:
            logger.debug(f"設定批量切換按鈕狀態失敗: {e}", "ModManagement")

    def toggle_local_mod(self, _event=None) -> None:
        """
        切換目前選取本地模組的啟用/停用狀態。

        Args:
            _event: 觸發切換的事件物件（可選）。目前未使用，但保留以符合事件處理器簽名。
        """
        if not self.local_tree:
            return
        if _event is not None and hasattr(_event, "y"):
            clicked_item = self.local_tree.identify_row(int(_event.y))
            if clicked_item:
                self.local_tree.selection_set(clicked_item)
        selection = self.local_tree.selection()
        if not selection:
            return
        item = selection[0]
        values = self.local_tree.item(item, "values")
        if not values or len(values) < 2:
            return
        mod_name = values[1]
        if not self.mod_manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return
        try:
            tags = self.local_tree.item(item, "tags")
            mod_id = tags[0] if tags and len(tags) > 0 else None
            if not mod_id:
                if hasattr(self, "status_label") and self.status_label.is_alive():
                    self.update_status(f"無法識別模組: {mod_name}")
                return
            mods_by_base_name: dict[str, Any] = {}
            for m in getattr(self, "local_mods", []) or []:
                base_name = m.filename.replace(".jar.disabled", "").replace(".jar", "")
                existing = mods_by_base_name.get(base_name)
                if existing is None or m.status == ModStatus.ENABLED:
                    mods_by_base_name[base_name] = m
            found_mod = mods_by_base_name.get(mod_id)
            if not found_mod:
                if hasattr(self, "status_label") and self.status_label.is_alive():
                    self.update_status(f"找不到模組檔案: {mod_id}")
                return
            manager = self.mod_manager
            tree = self.local_tree

            def do_toggle() -> None:
                self.ui_queue.put(lambda: self._set_bulk_controls_enabled(False))
                if not manager:
                    return
                old_filename = found_mod.filename
                old_file_path = getattr(found_mod, "file_path", "")
                action = "停用" if found_mod.status == ModStatus.ENABLED else "啟用"
                if found_mod.status == ModStatus.ENABLED:
                    result = manager.set_mod_state_result(mod_id, False)
                    new_status = ModStatus.DISABLED
                    new_filename = f"{mod_id}.jar.disabled"
                else:
                    result = manager.set_mod_state_result(mod_id, True)
                    new_status = ModStatus.ENABLED
                    new_filename = f"{mod_id}.jar"
                ok = result.completed

                def apply_ui_update() -> None:
                    try:
                        if ok:
                            self._apply_local_toggle_success(
                                tree=tree,
                                item_id=item,
                                mod_id=mod_id,
                                mod_obj=found_mod,
                                new_status=new_status,
                                new_filename=new_filename,
                                old_filename=old_filename,
                                old_file_path=old_file_path,
                            )
                            if hasattr(self, "status_label") and self.status_label.is_alive():
                                self.update_status(result.message or f"已{action}模組: {mod_name}")
                        else:
                            failure_message = result.message or f"{action}模組失敗: {mod_name}"
                            if hasattr(self, "status_label") and self.status_label.is_alive():
                                self.update_status(failure_message)
                            UIUtils.show_error(result.title or "錯誤", failure_message, self.parent)
                    finally:
                        self._set_bulk_controls_enabled(True)
                        self.update_selection_status()

                self.ui_queue.put(apply_ui_update)

            TaskUtils.run_async(do_toggle)
        except Exception as e:
            if hasattr(self, "status_label") and self.status_label.is_alive():
                self.update_status(f"操作失敗: {e}")
            logger.error(f"切換模組狀態錯誤: {e}\n{traceback.format_exc()}")

    def filter_local_mods(self, *_args) -> None:
        """
        篩選本地模組，使用 debounce 避免連續重建 Treeview。

        Args:
            *_args: 事件處理器的參數，未使用。
        """
        UIUtils.schedule_debounce(
            self.parent, "_local_filter_job", 120, self._run_debounced_local_filter_refresh, owner=self.frame
        )

    def _run_debounced_local_filter_refresh(self) -> None:
        self._local_filter_job = None
        self.refresh_local_list()

    def toggle_select_all(self) -> None:
        """切換全選/取消全選。"""
        try:
            if not self.local_tree:
                return
            items = self.local_tree.get_children()
            if not items:
                return
            if self.all_selected:
                self.local_tree.selection_remove(items)
                self.selected_mods.clear()
                self.all_selected = False
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            else:
                self.local_tree.selection_set(items)
                self.selected_mods.clear()
                for item in items:
                    mod_name = self._get_tree_item_mod_name(self.local_tree, item)
                    if mod_name:
                        self.selected_mods.add(mod_name)
                self.all_selected = True
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="❌ 取消全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            self.update_selection_status()
        except Exception as e:
            logger.error(f"切換全選失敗: {e}\n{traceback.format_exc()}")

    def batch_toggle_selected(self) -> None:
        """批量切換選中模組的啟用/停用狀態。"""
        try:
            if not self.mod_manager:
                UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
                return
            if not self.local_tree:
                return
            selected_items = self.local_tree.selection()
            if not selected_items:
                UIUtils.show_warning("提示", "請先選擇要操作的模組", self.parent)
                return
            mods_by_base_name: dict[str, Any] = {}
            for mod in getattr(self, "local_mods", []) or []:
                base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                existing = mods_by_base_name.get(base_name)
                if existing is None or mod.status == ModStatus.ENABLED:
                    mods_by_base_name[base_name] = mod
            selected_pairs = []
            seen = set()
            for tree_item_id in selected_items:
                base_name = self._get_tree_item_mod_id(self.local_tree, tree_item_id)
                if base_name and base_name not in seen:
                    seen.add(base_name)
                    selected_pairs.append((base_name, tree_item_id))
            selected_pairs = [(b, tid) for b, tid in selected_pairs if b in mods_by_base_name]
            if not selected_pairs:
                UIUtils.show_warning("提示", "找不到對應的模組檔案", self.parent)
                return
            manager = self.mod_manager

            def do_batch():
                total = len(selected_pairs)
                success_count = 0
                last_percent: float = -1
                self.ui_queue.put(lambda: self._set_bulk_controls_enabled(False))
                self.update_status_safe(f"正在批量切換 {total} 個模組狀態...")
                for idx, (base_name, tree_item_id) in enumerate(selected_pairs, start=1):
                    mod = mods_by_base_name.get(base_name)
                    if not mod:
                        continue
                    old_filename = getattr(mod, "filename", "")
                    old_file_path = getattr(mod, "file_path", "")
                    if mod.status == ModStatus.ENABLED:
                        result = manager.set_mod_state_result(base_name, False)
                        new_status = ModStatus.DISABLED
                        new_filename = f"{base_name}.jar.disabled"
                        action = "停用"
                    else:
                        result = manager.set_mod_state_result(base_name, True)
                        new_status = ModStatus.ENABLED
                        new_filename = f"{base_name}.jar"
                        action = "啟用"
                    ok = result.completed
                    if ok:
                        success_count += 1

                        def apply_row_update(
                            item_id=tree_item_id,
                            status=new_status,
                            mod_obj=mod,
                            mod_id=base_name,
                            filename=new_filename,
                            previous_filename=old_filename,
                            previous_file_path=old_file_path,
                        ) -> None:
                            try:
                                self._apply_local_toggle_success(
                                    tree=self.local_tree,
                                    item_id=item_id,
                                    mod_id=mod_id,
                                    mod_obj=mod_obj,
                                    new_status=status,
                                    new_filename=filename,
                                    old_filename=previous_filename,
                                    old_file_path=previous_file_path,
                                )
                            except Exception as e:
                                logger.debug(f"批量更新 UI row 失敗: {e}", "ModManagement")

                        self.ui_queue.put(apply_row_update)
                    else:
                        self.update_status_safe(result.message or f"{action}模組失敗: {base_name}")
                    percent = idx / total * 100 if total else 0
                    if int(percent) != int(last_percent):
                        last_percent = percent
                        self.update_progress_safe(percent)
                self.update_progress_safe(0)
                self.update_status_safe(f"已切換 {success_count}/{total} 個模組狀態")
                self.ui_queue.put(self.update_selection_status)
                self.ui_queue.put(lambda: self._set_bulk_controls_enabled(True))

            TaskUtils.run_async(do_batch)
        except Exception as e:
            logger.error(f"批量操作失敗: {e}\n{traceback.format_exc()}")
            self.update_progress_safe(0)
            UIUtils.show_error("錯誤", f"批量操作失敗: {e}", self.parent)

    def update_selection_status(self) -> None:
        """更新選擇狀態顯示。"""
        if not self.local_tree:
            return
        try:
            selected_count = len(self.local_tree.selection())
            total_count = len(self.local_tree.get_children())
            if selected_count > 0:
                status_text = f"已選擇 {selected_count}/{total_count} 個模組"
            else:
                status_text = f"找到 {total_count} 個模組"
            if hasattr(self, "status_label"):
                self.status_label.configure(text=status_text)
        except Exception as e:
            logger.error(f"更新選擇狀態失敗: {e}\n{traceback.format_exc()}")

    def on_tree_selection_changed(self, _event=None) -> None:
        """
        本地模組樹狀檢視選擇變更時同步狀態。

        Args:
            _event: 觸發選擇變更的事件物件（可選）。目前未使用，但保留以符合事件處理器簽名。
        """
        if not self.local_tree:
            return
        try:
            self.update_selection_status()
            self.selected_mods.clear()
            selected_items = self.local_tree.selection()
            for item in selected_items:
                mod_name = self._get_tree_item_mod_name(self.local_tree, item)
                if mod_name:
                    self.selected_mods.add(mod_name)
            total_items = len(self.local_tree.get_children())
            selected_items_count = len(selected_items)
            if selected_items_count == 0:
                self.all_selected = False
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            elif selected_items_count == total_items:
                self.all_selected = True
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="❌ 取消全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
        except Exception as e:
            logger.error(f"處理選擇變化失敗: {e}\n{traceback.format_exc()}")


__all__ = ["LocalModListPresenter"]
