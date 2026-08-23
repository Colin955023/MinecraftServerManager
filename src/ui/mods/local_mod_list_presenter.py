"""本地模組列表 Presenter"""

from __future__ import annotations

import time
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QVBoxLayout
from qfluentwidgets import PushButton, SearchLineEdit, TreeWidget

from src.core import get_modrinth_project_info
from src.models import ModOperationScope, ModStatus
from src.ui import mod_management_logger as logger
from src.utils import (
    Colors,
    ScrollableComboBox,
    Sizes,
    Spacing,
    UIUtils,
    Variable,
    apply_table_header_style,
    resolve_color,
)


class LocalModListPresenter:
    """封裝本地模組列表的 UI 建立、篩選、選取與批次操作"""

    def __init__(self, frame: Any):
        self.frame = frame
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

    def create_local_toolbar(self) -> None:
        """建立本地模組工具列"""
        toolbar_frame = QFrame(self.frame.local_tab)
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM)
        if self.frame.local_tab.layout():
            self.frame.local_tab.layout().addWidget(toolbar_frame)

        left_frame = QFrame(toolbar_frame)
        left_layout = QHBoxLayout(left_frame)
        left_layout.setContentsMargins(Spacing.SMALL, 0, 0, 0)
        left_layout.setSpacing(12)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        toolbar_layout.addWidget(left_frame)

        import_btn = PushButton("📁 匯入模組", left_frame)
        import_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        import_btn.clicked.connect(self.frame.import_mod_file)
        left_layout.addWidget(import_btn)

        refresh_mod_list_btn = PushButton("🔄 重新整理", left_frame)
        refresh_mod_list_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        refresh_mod_list_btn.clicked.connect(self.refresh_mod_list_force)
        left_layout.addWidget(refresh_mod_list_btn)

        update_btn = PushButton("🔄 檢查更新", left_frame)
        update_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        update_btn.clicked.connect(self.frame.check_local_mod_updates)
        left_layout.addWidget(update_btn)

        self.frame.select_all_btn = PushButton("☑️ 全選", left_frame)
        self.frame.select_all_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        self.frame.select_all_btn.clicked.connect(self.toggle_select_all)
        left_layout.addWidget(self.frame.select_all_btn)

        self.frame.batch_toggle_btn = PushButton("🔄 批次切換", left_frame)
        self.frame.batch_toggle_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        self.frame.batch_toggle_btn.clicked.connect(self.batch_toggle_selected)
        left_layout.addWidget(self.frame.batch_toggle_btn)

        folder_btn = PushButton("📂 開啟資料夾", left_frame)
        folder_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        folder_btn.clicked.connect(self.frame.open_mods_folder)
        left_layout.addWidget(folder_btn)

        toolbar_layout.addStretch(1)

        right_frame = QFrame(toolbar_frame)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(0, 0, Spacing.LARGE, 0)
        right_layout.setSpacing(Spacing.SMALL_PLUS)
        toolbar_layout.addWidget(right_frame)

        search_filter_layout = QHBoxLayout()
        search_filter_layout.setContentsMargins(0, 0, 0, 0)
        search_filter_layout.setSpacing(Spacing.LARGE)

        self.frame.local_search_var = Variable(value="")
        search_entry = SearchLineEdit(right_frame)
        search_entry.setPlaceholderText("搜尋本地模組")
        search_entry.textChanged.connect(self.frame.local_search_var.set)
        self.frame.local_search_var.trace("w", self.filter_local_mods)
        search_filter_layout.addWidget(search_entry)

        self.frame.local_filter_var = Variable(value="所有")
        filter_combo = ScrollableComboBox(right_frame)
        filter_combo.addItems(["所有", "啟用", "停用"])
        filter_combo.currentTextChanged.connect(self.frame.local_filter_var.set)
        self.frame.local_filter_var.trace("w", self.filter_local_mods)
        search_filter_layout.addWidget(filter_combo)

        right_layout.addLayout(search_filter_layout)

        export_btn = PushButton("匯出模組清單", right_frame)
        export_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        export_btn.clicked.connect(self.frame.export_mod_list_dialog)
        right_layout.addWidget(export_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def refresh_mod_list_force(self, _event=None) -> None:
        """
        強制重新掃描本地模組並重繪列表

        Args:
            _event: 事件物件（未使用）
        """
        if self.frame.mod_manager:
            manager = self.frame.mod_manager
            session = self.frame.mod_session
            scope = session.begin_local_scan()

            def load_thread():
                try:
                    self.frame.update_status_safe("正在強制重新掃描本地模組...")
                    if hasattr(manager, "clear_mod_index"):
                        manager.clear_mod_index()

                    mods = list(manager.scan_mods())
                    if not session.accept_local_results(scope, mods):
                        return
                    session.update_local_scan_fingerprint(None, None, None)
                    self.frame.ui_queue.put(self.frame.refresh_local_list)
                    self.enhance_local_mods(scope)
                    self.frame.update_status_safe(f"找到 {len(mods)} 個本地模組 (已重新整理)")
                except Exception as e:
                    logger.error(f"強制掃描失敗: {e}\n{traceback.format_exc()}")
                    if session.is_scope_current(scope):
                        self.frame.update_status_safe(f"強制掃描失敗: {e}")

            self.frame.scope.submit(load_thread, key="local_force_scan", replace=True)

    def create_local_mod_list(self) -> None:
        """建立本地模組列表"""
        list_frame = QFrame(self.frame.local_tab)
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(Spacing.SMALL_PLUS, 0, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)
        if self.frame.local_tab.layout():
            self.frame.local_tab.layout().addWidget(list_frame, stretch=1)

        tree_container = QFrame(list_frame)
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(Spacing.SMALL_PLUS, 0, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)
        list_layout.addWidget(tree_container, stretch=1)

        self.frame.local_tree = TreeWidget(tree_container)
        tree = self.frame.local_tree
        tree.setColumnCount(8)
        tree.setHeaderLabels(["狀態", "模組名稱", "版本", "作者", "載入器", "檔案大小", "修改時間", "描述"])
        apply_table_header_style(tree)

        for i in range(8):
            tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        tree.header().setStretchLastSection(True)

        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.setRootIsDecorated(False)
        tree.setIndentation(0)

        tree.itemDoubleClicked.connect(self._on_local_item_double_clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.frame.show_local_context_menu)
        tree.itemSelectionChanged.connect(self.on_tree_selection_changed)

        tree_layout.addWidget(tree, stretch=1)

    def _on_local_item_double_clicked(self) -> None:
        """只在滑鼠左鍵雙擊時切換模組狀態"""
        if QApplication.mouseButtons() == Qt.MouseButton.RightButton:
            return
        self.toggle_local_mod()

    def apply_local_tree_theme(self) -> None:
        """重新套用本地模組清單的主題色與交錯列文字色"""
        tree = self.frame.local_tree
        if not tree:
            return
        from qfluentwidgets import isDarkTheme

        is_dark = isDarkTheme()
        bg_color = resolve_color((Colors.BG_CARD_LIGHT, Colors.BG_CARD_DARK), dark=is_dark)
        border_color = resolve_color(Colors.BORDER, dark=is_dark)
        primary_color = resolve_color(Colors.TEXT_PRIMARY, dark=is_dark)
        muted_color = resolve_color(Colors.TEXT_MUTED, dark=is_dark)

        header_bg = resolve_color((Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_DARK), dark=is_dark)
        header_border = resolve_color(Colors.TABLE_HEADER_BORDER, dark=is_dark)
        tree.setStyleSheet(
            f"TreeWidget, QTreeWidget {{ background-color: {bg_color}; color: {primary_color}; border: 1px solid {border_color}; border-radius: 6px; }}\n"
            f"QHeaderView {{ background-color: transparent; border: none; }}\n"
            f"QHeaderView::section {{ background-color: {header_bg}; color: {primary_color}; border: {Sizes.TABLE_HEADER_BORDER_WIDTH}px solid {header_border}; padding: 4px 6px; }}"
        )

        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if item is None:
                continue
            color = muted_color if "已停用" in item.text(0) else primary_color
            brush = QBrush(QColor(color))
            for column in range(tree.columnCount()):
                if item.foreground(column) != brush:
                    item.setForeground(column, brush)

    def load_local_mods(self) -> None:
        """載入本地模組，並同步清空增強 cache，確保顯示一致"""
        if not self.frame.mod_manager:
            return
        manager = self.frame.mod_manager
        session = self.frame.mod_session
        scope = session.begin_local_scan()
        current_server = session.server
        server_path_key = self._get_current_server_path_key(current_server)
        mods_dir = Path(server_path_key) / "mods" if server_path_key else None
        mods_dir_key = str(mods_dir.resolve()) if mods_dir else ""

        mods_dir_signature = self._build_mods_dir_signature(mods_dir)
        try:
            mods_dir_mtime = mods_dir.stat().st_mtime if mods_dir and mods_dir.exists() else None
        except Exception:
            mods_dir_mtime = None
        last_mods_dir, _last_mtime, last_signature = session.local_scan_fingerprint()
        if (
            mods_dir_key
            and mods_dir_key == last_mods_dir
            and (mods_dir_signature is not None)
            and (mods_dir_signature == last_signature)
        ):
            self.frame.update_status_safe(f"找到 {len(session.local_mods)} 個本地模組")
            self.frame.ui_queue.put(self.frame.refresh_local_list)
            return

        def load_thread():
            try:
                self.frame.update_status_safe("正在掃描本地模組...")
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
                    if not session.is_scope_current(scope):
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
                        self.frame.update_progress_safe(percent)
                current_signature = self._build_mods_dir_signature(mods_dir)
                if current_signature is None:
                    current_signature = mods_dir_signature
                if not session.is_scope_current(scope):
                    return
                if current_signature != mods_dir_signature:
                    return
                if not session.accept_local_results(scope, new_local_mods):
                    return
                try:
                    accepted_mtime = mods_dir.stat().st_mtime if mods_dir and mods_dir.exists() else None
                except Exception:
                    accepted_mtime = mods_dir_mtime
                session.update_local_scan_fingerprint(mods_dir_key, accepted_mtime, current_signature)
                self.frame.ui_queue.put(self.frame.refresh_local_list)
                self.enhance_local_mods(scope)
                self.frame.update_status_safe(f"找到 {len(mods)} 個本地模組")
            except Exception as e:
                logger.error(f"掃描失敗: {e}\n{traceback.format_exc()}")
                if session.is_scope_current(scope):
                    self.frame.update_progress_safe(0)
                    self.frame.update_status_safe(f"掃描失敗: {e}")

        self.frame.scope.submit(load_thread, key="local_scan", replace=True)

    def enhance_local_mods(self, scope: ModOperationScope | None = None) -> None:
        """查詢本地模組增強資訊，並只接受目前工作階段的結果

        Args:
            scope: 選用的既有操作 scope；省略時建立新的本地掃描 scope
        """
        session = self.frame.mod_session
        manager = self.frame.mod_manager
        if manager is None:
            return
        if scope is None:
            scope = session.begin_local_scan()
            if not session.accept_local_results(scope, list(session.local_mods)):
                return
        if not session.is_scope_current(scope):
            return

        def enhance_single(mod):
            try:
                if not session.is_scope_current(scope):
                    return
                if session.get_provider_cache(mod.filename) is not None:
                    return
                project_id = str(getattr(mod, "platform_id", "") or "").strip()
                if not project_id:
                    return
                enhanced = get_modrinth_project_info(project_id)
                if enhanced:
                    if not session.is_scope_current(scope):
                        return
                    if not session.cache_provider_enhancement(scope, mod.filename, enhanced):
                        return
                    time.sleep(0.05)
            except Exception as e:
                logger.error(f"模組 {mod.filename} 資訊失敗: {e}\n{traceback.format_exc()}")

        def enhance_thread():
            if not session.is_scope_current(scope):
                return
            for mod in session.local_mods:
                if not session.is_scope_current(scope):
                    return
                enhance_single(mod)
            if not session.is_scope_current(scope):
                return
            self.frame.ui_queue.put(self.frame.refresh_local_list)

        self.frame.scope.submit(enhance_thread, key="local_enhance", replace=True)

    def toggle_local_mod(self, _event=None) -> None:
        """
        切換目前選取本地模組的啟用/停用狀態

        Args:
            _event: 觸發切換的事件物件（可選）
        """
        tree = self.frame.local_tree
        if not tree:
            return

        selected_items = tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        mod_name = item.text(1)

        if not self.frame.mod_manager:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.frame.parent, message_level="error")
            return

        try:
            mod_id = item.data(0, Qt.ItemDataRole.UserRole)
            row = tree.indexOfTopLevelItem(item)
            if not mod_id:
                self.frame.update_status(f"無法識別模組: {mod_name}")
                return

            mods_by_base_name: dict[str, Any] = {}
            for m in self.frame.mod_session.local_mods:
                base_name = m.filename.replace(".jar.disabled", "").replace(".jar", "")
                existing = mods_by_base_name.get(base_name)
                if existing is None or m.status == ModStatus.ENABLED:
                    mods_by_base_name[base_name] = m

            found_mod = mods_by_base_name.get(mod_id)
            if not found_mod:
                self.frame.update_status(f"找不到模組檔案: {mod_id}")
                return

            manager = self.frame.mod_manager

            def do_toggle() -> None:
                self._set_bulk_controls_enabled(False)
                if not manager:
                    return
                old_filename = found_mod.filename
                old_file_path = getattr(found_mod, "file_path", "")
                action = "停用" if found_mod.status == ModStatus.ENABLED else "啟用"
                if found_mod.status == ModStatus.ENABLED:
                    result = manager.set_mod_state_result(mod_id, False, notify_change=False)
                    new_status = ModStatus.DISABLED
                    new_filename = f"{mod_id}.jar.disabled"
                else:
                    result = manager.set_mod_state_result(mod_id, True, notify_change=False)
                    new_status = ModStatus.ENABLED
                    new_filename = f"{mod_id}.jar"
                ok = result.completed

                def apply_ui_update() -> None:
                    try:
                        if ok:
                            self.frame._apply_local_toggle_success(
                                tree=tree,
                                item_id=row,
                                _mod_id=mod_id,
                                mod_obj=found_mod,
                                new_status=new_status,
                                new_filename=new_filename,
                                old_filename=old_filename,
                                old_file_path=old_file_path,
                            )
                            self.frame.update_status(result.message or f"已{action}模組: {mod_name}")
                        else:
                            failure_message = result.message or f"{action}模組失敗: {mod_name}"
                            self.frame.update_status(failure_message)
                            UIUtils.show_message(
                                result.title or "錯誤", failure_message, self.frame.parent, message_level="error"
                            )
                    finally:
                        self._set_bulk_controls_enabled(True)
                        self.update_selection_status()

                apply_ui_update()

            do_toggle()
        except Exception as e:
            self.frame.update_status(f"操作失敗: {e}")
            logger.error(f"切換模組狀態錯誤: {e}\n{traceback.format_exc()}")

    def filter_local_mods(self, *_args) -> None:
        """
        篩選本地模組，使用 debounce 避免連續重建 Treeview

        Args:
            *_args: 事件處理器的參數，未使用
        """
        UIUtils.schedule_debounce(
            self.frame.parent, "_local_filter_job", 120, self._run_debounced_local_filter_refresh, owner=self.frame
        )

    def toggle_select_all(self, _event=None) -> None:
        """
        全選或取消全選列表中的模組

        Args:
            _event: 事件物件（未使用）
        """
        tree = self.frame.local_tree
        if not tree:
            return

        new_state = not getattr(self, "all_selected", False)
        self.all_selected = new_state
        row_count = tree.topLevelItemCount()
        for i in range(row_count):
            item = tree.topLevelItem(i)
            if item:
                item.setSelected(new_state)

        if hasattr(self.frame.select_all_btn, "setText"):
            self.frame.select_all_btn.setText("❌ 取消全選" if new_state else "☑️ 全選")
        self.update_selection_status()

    def batch_toggle_selected(self, _event=None) -> None:
        """
        批量切換選中模組的啟用/停用狀態

        Args:
            _event: 事件物件（未使用）
        """
        try:
            if not self.frame.mod_manager:
                UIUtils.show_message("錯誤", "模組管理器未初始化", self.frame.parent, message_level="error")
                return
            tree = self.frame.local_tree
            if not tree:
                return

            selected_items = tree.selectedItems()
            if not selected_items:
                UIUtils.show_message("提示", "請先選擇要操作的模組", self.frame.parent, message_level="warning")
                return

            mods_by_base_name: dict[str, Any] = {}
            for mod in self.frame.mod_session.local_mods:
                base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                existing = mods_by_base_name.get(base_name)
                if existing is None or mod.status == ModStatus.ENABLED:
                    mods_by_base_name[base_name] = mod

            selected_pairs = []
            seen = set()
            for item in selected_items:
                base_name = item.data(0, Qt.ItemDataRole.UserRole)
                if base_name and base_name not in seen:
                    seen.add(base_name)
                    row = tree.indexOfTopLevelItem(item)
                    selected_pairs.append((base_name, row))

            selected_pairs = [(b, r) for b, r in selected_pairs if b in mods_by_base_name]
            if not selected_pairs:
                UIUtils.show_message("提示", "找不到對應的模組檔案", self.frame.parent, message_level="warning")
                return

            manager = self.frame.mod_manager

            def do_batch():
                total = len(selected_pairs)
                success_count = 0
                last_percent: float = -1
                self._set_bulk_controls_enabled(False)
                self.frame.update_status_safe(f"正在批次切換 {total} 個模組狀態...")
                for idx, (base_name, row) in enumerate(selected_pairs, start=1):
                    mod = mods_by_base_name.get(base_name)
                    if not mod:
                        continue
                    old_filename = getattr(mod, "filename", "")
                    old_file_path = getattr(mod, "file_path", "")
                    if mod.status == ModStatus.ENABLED:
                        result = manager.set_mod_state_result(base_name, False, notify_change=False)
                        new_status = ModStatus.DISABLED
                        new_filename = f"{base_name}.jar.disabled"
                        action = "停用"
                    else:
                        result = manager.set_mod_state_result(base_name, True, notify_change=False)
                        new_status = ModStatus.ENABLED
                        new_filename = f"{base_name}.jar"
                        action = "啟用"
                    ok = result.completed
                    if ok:
                        success_count += 1

                        def apply_row_update(
                            item_id=row,
                            status=new_status,
                            mod_obj=mod,
                            mod_id=base_name,
                            filename=new_filename,
                            previous_filename=old_filename,
                            previous_file_path=old_file_path,
                        ) -> None:
                            try:
                                self.frame._apply_local_toggle_success(
                                    tree=tree,
                                    item_id=item_id,
                                    _mod_id=mod_id,
                                    mod_obj=mod_obj,
                                    new_status=status,
                                    new_filename=filename,
                                    old_filename=previous_filename,
                                    old_file_path=previous_file_path,
                                )
                            except Exception as e:
                                logger.debug(f"批次更新 UI row 失敗: {e}")

                        apply_row_update()
                    else:
                        self.frame.update_status_safe(result.message or f"{action}模組失敗: {base_name}")
                    percent = idx / total * 100 if total else 0
                    if int(percent) != int(last_percent):
                        last_percent = percent
                        self.frame.update_progress_safe(percent)

                def apply_final_update() -> None:
                    self._set_bulk_controls_enabled(True)
                    self.update_selection_status()
                    self.frame.update_status(f"批次操作完成，成功切換 {success_count}/{total} 個模組")
                    self.frame.update_progress_safe(0)

                apply_final_update()

            do_batch()
        except Exception as e:
            logger.error(f"批次操作失敗: {e}\n{traceback.format_exc()}")
            self.frame.update_progress_safe(0)
            UIUtils.show_message("錯誤", f"批次操作失敗: {e}", self.frame.parent, message_level="error")

    def get_online_version_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """
        根據檔案雜湊值查詢線上版本資訊

        Args:
            file_hash: 檔案的雜湊值，用於查詢對應的線上版本資訊

        Returns:
            如果找到對應的線上版本資訊，回傳包含版本資訊的字典；若未找到則回傳 None
        """
        if hasattr(self.frame, "get_online_version_by_hash"):
            return self.frame.get_online_version_by_hash(file_hash)
        return None

    def update_selection_status(self) -> None:
        """更新選擇狀態顯示"""
        tree = self.frame.local_tree
        if not tree:
            return
        try:
            total_count = tree.topLevelItemCount()
            selected_count = len(tree.selectedItems())

            if self.frame.batch_toggle_btn:
                self.frame.batch_toggle_btn.setEnabled(selected_count > 0)

            if selected_count > 0:
                status_text = f"已選擇 {selected_count} / {total_count} 個模組"
            else:
                status_text = f"找到 {total_count} 個模組"
            self.frame.mod_session.set_status(status_text)
            if hasattr(self.frame.status_label, "setText"):
                self.frame.status_label.setText(status_text)
        except Exception as e:
            logger.error(f"更新選擇狀態失敗: {e}\n{traceback.format_exc()}")

    def on_tree_selection_changed(self, _event=None) -> None:
        """
        本地模組樹狀檢視選擇變更時同步狀態

        Args:
            _event: 觸發選擇變更的事件物件（可選）
        """
        tree = self.frame.local_tree
        if not tree:
            return
        try:
            self.update_selection_status()

            selected_items = tree.selectedItems()
            self.frame.mod_session.replace_selection(
                {
                    str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
                    for item in selected_items
                    if str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
                }
            )

            total_items = tree.topLevelItemCount()
            selected_items_count = len(selected_items)

            if selected_items_count == 0:
                self.all_selected = False
                try:
                    if hasattr(self.frame.select_all_btn, "setText"):
                        self.frame.select_all_btn.setText("☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            elif selected_items_count == total_items and total_items > 0:
                self.all_selected = True
                try:
                    if hasattr(self.frame.select_all_btn, "setText"):
                        self.frame.select_all_btn.setText("❌ 取消全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            else:
                self.all_selected = False
                try:
                    if hasattr(self.frame.select_all_btn, "setText"):
                        self.frame.select_all_btn.setText("☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
        except Exception as e:
            logger.error(f"處理選擇變化失敗: {e}\n{traceback.format_exc()}")

    def _set_bulk_controls_enabled(self, enabled: bool) -> None:
        """設定批次操作控制元件的啟用/停用狀態"""
        with suppress(Exception):
            if self.frame.select_all_btn:
                self.frame.select_all_btn.setEnabled(enabled)
        with suppress(Exception):
            if self.frame.batch_toggle_btn:
                self.frame.batch_toggle_btn.setEnabled(enabled)

    def _run_debounced_local_filter_refresh(self) -> None:
        self.frame._local_filter_job = None
        self.frame.refresh_local_list()


__all__ = ["LocalModListPresenter"]
