"""本地模組列表 Presenter"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QVBoxLayout
from qfluentwidgets import PushButton, SearchLineEdit, TreeWidget

from ....models import ModStatus
from ....utils import ScrollableComboBox, Sizes, Spacing, TaskUtils, UIUtils, Variable, get_shared_manager
from ..mod_search_service.modrinth_service import enhance_local_mod
from .constants import logger
from .presenter_delegate_mixin import PresenterDelegateMixin


class LocalModListPresenter(PresenterDelegateMixin):
    """封裝本地模組列表的 UI 建立、篩選、選取與批次操作"""

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

    def create_local_toolbar(self) -> None:
        """建立本地模組工具列"""
        toolbar_frame = QFrame(self.local_tab)
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM)
        if self.local_tab.layout():
            self.local_tab.layout().addWidget(toolbar_frame)

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

        self.select_all_btn = PushButton("☑️ 全選", left_frame)
        self.select_all_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        self.select_all_btn.clicked.connect(self.toggle_select_all)
        left_layout.addWidget(self.select_all_btn)

        self.batch_toggle_btn = PushButton("🔄 批量切換", left_frame)
        self.batch_toggle_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        self.batch_toggle_btn.clicked.connect(self.batch_toggle_selected)
        left_layout.addWidget(self.batch_toggle_btn)

        folder_btn = PushButton("📂 開啟資料夾", left_frame)
        folder_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        folder_btn.clicked.connect(self.frame.open_mods_folder)
        left_layout.addWidget(folder_btn)

        toolbar_layout.addStretch(1)

        right_frame = QFrame(toolbar_frame)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(0, 0, Spacing.LARGE_MINUS, 0)
        right_layout.setSpacing(Spacing.SMALL_PLUS)
        toolbar_layout.addWidget(right_frame)

        search_filter_layout = QHBoxLayout()
        search_filter_layout.setContentsMargins(0, 0, 0, 0)
        search_filter_layout.setSpacing(Spacing.LARGE_MINUS)

        self.local_search_var = Variable(value="")
        search_entry = SearchLineEdit(right_frame)
        search_entry.setPlaceholderText("搜尋本地模組")
        search_entry.textChanged.connect(self.local_search_var.set)
        self.local_search_var.trace("w", self.filter_local_mods)
        search_filter_layout.addWidget(search_entry)

        self.local_filter_var = Variable(value="所有")
        filter_combo = ScrollableComboBox(right_frame)
        filter_combo.addItems(["所有", "啟用", "停用"])
        filter_combo.currentTextChanged.connect(self.local_filter_var.set)
        self.local_filter_var.trace("w", self.filter_local_mods)
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
        if self.mod_manager:
            manager = self.mod_manager

            def load_thread():
                try:
                    self.update_status_safe("正在強制重新掃描本地模組...")
                    mods = manager.scan_mods()
                    self.local_mods = mods
                    self.enhanced_mods_cache = {}
                    if hasattr(self, "refresh_local_list"):
                        self.ui_queue.put(self.refresh_local_list)
                    self.enhance_local_mods()
                    self.update_status_safe(f"找到 {len(mods)} 個本地模組 (已重新整理)")
                except Exception as e:
                    logger.bind(component="").error(
                        f"強制掃描失敗: {e}\n{traceback.format_exc()}", component="ModManagementFrame"
                    )
                    self.update_status_safe(f"強制掃描失敗: {e}")

            TaskUtils.run_async(load_thread)

    def create_local_mod_list(self) -> None:
        """建立本地模組列表"""
        list_frame = QFrame(self.local_tab)
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(Spacing.SMALL_PLUS, 0, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)
        if self.local_tab.layout():
            self.local_tab.layout().addWidget(list_frame, stretch=1)

        tree_container = QFrame(list_frame)
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(Spacing.SMALL_PLUS, 0, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)
        list_layout.addWidget(tree_container, stretch=1)

        self.local_tree = TreeWidget(tree_container)
        self.local_tree.setColumnCount(8)
        self.local_tree.setHeaderLabels(["狀態", "模組名稱", "版本", "作者", "載入器", "檔案大小", "修改時間", "描述"])

        for i in range(8):
            self.local_tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.local_tree.header().setStretchLastSection(True)

        self.local_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.local_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.local_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.local_tree.doubleClicked.connect(self.toggle_local_mod)
        self.local_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.local_tree.customContextMenuRequested.connect(self.show_local_context_menu)
        self.local_tree.itemSelectionChanged.connect(self.on_tree_selection_changed)

        tree_layout.addWidget(self.local_tree, stretch=1)

    def apply_local_tree_theme(self) -> None:
        """重新套用本地模組清單的主題色與交錯列文字色"""
        if not self.local_tree:
            return

    def load_local_mods(self) -> None:
        """載入本地模組，並同步清空增強 cache，確保顯示一致"""
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
                        logger.debug("略過過期的本地模組掃描結果", component="ModManagementFrame")
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
                    logger.debug("略過過期的本地模組掃描結果", component="ModManagementFrame")
                    return
                if current_signature != mods_dir_signature:
                    logger.debug("本地模組目錄在掃描期間已變更，略過過期結果", component="ModManagementFrame")
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
        """查詢本地模組增強資訊，查詢完成後刷新列表

        Args:
            request_token: 用來比對目前是否仍為同一輪載入的 token
            server_path_key: 目前伺服器路徑的正規化快照，用來避免伺服器切換後寫回舊結果
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
                    f"模組 {mod.filename} 資訊失敗: {e}\n{traceback.format_exc()}", component="ModManagementFrame"
                )

        def enhance_thread():
            if not self._is_local_mods_scope_current(request_token, server_path_key):
                return
            futures = [get_shared_manager().run(enhance_single, mod) for mod in list(self.local_mods)]
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    logger.debug(f"模組增強背景工作失敗: {e}", component="ModManagementFrame")
            if not self._is_local_mods_scope_current(request_token, server_path_key):
                return
            self.ui_queue.put(self.refresh_local_list)

        TaskUtils.run_async(enhance_thread)

    def toggle_local_mod(self, _event=None) -> None:
        """
        切換目前選取本地模組的啟用/停用狀態

        Args:
            _event: 觸發切換的事件物件（可選）
        """
        if not self.local_tree:
            return

        selected_items = self.local_tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        mod_name = item.text(1)

        if not self.mod_manager:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.parent, message_level="error")
            return

        try:
            mod_id = item.data(0, Qt.ItemDataRole.UserRole)
            row = self.local_tree.indexOfTopLevelItem(item)
            if not mod_id:
                if hasattr(self, "status_label") and hasattr(self.status_label, "setText"):
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
                if hasattr(self, "status_label") and hasattr(self.status_label, "setText"):
                    self.update_status(f"找不到模組檔案: {mod_id}")
                return

            manager = self.mod_manager
            tree = self.local_tree

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
                            self._apply_local_toggle_success(
                                tree=tree,
                                item_id=row,
                                _mod_id=mod_id,
                                mod_obj=found_mod,
                                new_status=new_status,
                                new_filename=new_filename,
                                old_filename=old_filename,
                                old_file_path=old_file_path,
                            )
                            if hasattr(self, "status_label") and hasattr(self.status_label, "setText"):
                                self.update_status(result.message or f"已{action}模組: {mod_name}")
                        else:
                            failure_message = result.message or f"{action}模組失敗: {mod_name}"
                            if hasattr(self, "status_label") and hasattr(self.status_label, "setText"):
                                self.update_status(failure_message)
                            UIUtils.show_message(
                                result.title or "錯誤", failure_message, self.parent, message_level="error"
                            )
                    finally:
                        self._set_bulk_controls_enabled(True)
                        self.update_selection_status()

                apply_ui_update()

            do_toggle()
        except Exception as e:
            if hasattr(self, "status_label") and hasattr(self.status_label, "setText"):
                self.update_status(f"操作失敗: {e}")
            logger.error(f"切換模組狀態錯誤: {e}\n{traceback.format_exc()}")

    def filter_local_mods(self, *_args) -> None:
        """
        篩選本地模組，使用 debounce 避免連續重建 Treeview

        Args:
            *_args: 事件處理器的參數，未使用
        """
        UIUtils.schedule_debounce(
            self.parent, "_local_filter_job", 120, self._run_debounced_local_filter_refresh, owner=self.frame
        )

    def toggle_select_all(self, _event=None) -> None:
        """
        全選或取消全選列表中的模組

        Args:
            _event: 事件物件（未使用）
        """
        if not self.local_tree:
            return

        new_state = not getattr(self, "all_selected", False)
        self.all_selected = new_state
        row_count = self.local_tree.topLevelItemCount()
        for i in range(row_count):
            item = self.local_tree.topLevelItem(i)
            if item:
                item.setSelected(new_state)

        if hasattr(self, "select_all_btn") and hasattr(self.select_all_btn, "setText"):
            self.select_all_btn.setText("❌ 取消全選" if new_state else "☑️ 全選")
        self.update_selection_status()

    def batch_toggle_selected(self, _event=None) -> None:
        """
        批量切換選中模組的啟用/停用狀態

        Args:
            _event: 事件物件（未使用）
        """
        try:
            if not self.mod_manager:
                UIUtils.show_message("錯誤", "模組管理器未初始化", self.parent, message_level="error")
                return
            if not self.local_tree:
                return

            selected_items = self.local_tree.selectedItems()
            if not selected_items:
                UIUtils.show_message("提示", "請先選擇要操作的模組", self.parent, message_level="warning")
                return

            mods_by_base_name: dict[str, Any] = {}
            for mod in getattr(self, "local_mods", []) or []:
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
                    row = self.local_tree.indexOfTopLevelItem(item)
                    selected_pairs.append((base_name, row))

            selected_pairs = [(b, r) for b, r in selected_pairs if b in mods_by_base_name]
            if not selected_pairs:
                UIUtils.show_message("提示", "找不到對應的模組檔案", self.parent, message_level="warning")
                return

            manager = self.mod_manager

            def do_batch():
                total = len(selected_pairs)
                success_count = 0
                last_percent: float = -1
                self._set_bulk_controls_enabled(False)
                self.update_status_safe(f"正在批量切換 {total} 個模組狀態...")
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
                                self._apply_local_toggle_success(
                                    tree=self.local_tree,
                                    item_id=item_id,
                                    _mod_id=mod_id,
                                    mod_obj=mod_obj,
                                    new_status=status,
                                    new_filename=filename,
                                    old_filename=previous_filename,
                                    old_file_path=previous_file_path,
                                )
                            except Exception as e:
                                logger.debug(f"批量更新 UI row 失敗: {e}")

                        apply_row_update()
                    else:
                        self.update_status_safe(result.message or f"{action}模組失敗: {base_name}")
                    percent = idx / total * 100 if total else 0
                    if int(percent) != int(last_percent):
                        last_percent = percent
                        self.update_progress_safe(percent)

                def apply_final_update() -> None:
                    self._set_bulk_controls_enabled(True)
                    self.update_selection_status()
                    self.update_status(f"批量操作完成，成功切換 {success_count}/{total} 個模組")
                    self.update_progress_safe(0)

                apply_final_update()

            do_batch()
        except Exception as e:
            logger.error(f"批量操作失敗: {e}\n{traceback.format_exc()}")
            self.update_progress_safe(0)
            UIUtils.show_message("錯誤", f"批量操作失敗: {e}", self.parent, message_level="error")

    def get_online_version_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        """
        根據檔案雜湊值查詢線上版本資訊

        Args:
            file_hash: 檔案的雜湊值，用於查詢對應的線上版本資訊

        Returns:
            dict: 如果找到對應的線上版本資訊，返回一個字典，包含版本資訊；如果未找到，返回 None
        """
        if hasattr(self.frame, "get_online_version_by_hash"):
            return self.frame.get_online_version_by_hash(file_hash)
        return None

    def update_selection_status(self) -> None:
        """更新選擇狀態顯示"""
        if not self.local_tree:
            return
        try:
            total_count = self.local_tree.topLevelItemCount()
            selected_count = len(self.local_tree.selectedItems())

            if hasattr(self, "batch_toggle_btn") and self.batch_toggle_btn:
                self.batch_toggle_btn.setEnabled(selected_count > 0)

            if selected_count > 0:
                status_text = f"已選擇 {selected_count} / {total_count} 個模組"
            else:
                status_text = f"找到 {total_count} 個模組"
            if hasattr(self, "status_label") and hasattr(self.status_label, "setText"):
                self.status_label.setText(status_text)
        except Exception as e:
            logger.error(f"更新選擇狀態失敗: {e}\n{traceback.format_exc()}")

    def on_tree_selection_changed(self, _event=None) -> None:
        """
        本地模組樹狀檢視選擇變更時同步狀態

        Args:
            _event: 觸發選擇變更的事件物件（可選）
        """
        if not self.local_tree:
            return
        try:
            self.update_selection_status()
            self.selected_mods.clear()

            selected_items = self.local_tree.selectedItems()
            for item in selected_items:
                self.selected_mods.add(item.text(1))

            total_items = self.local_tree.topLevelItemCount()
            selected_items_count = len(selected_items)

            if selected_items_count == 0:
                self.all_selected = False
                try:
                    if hasattr(self.select_all_btn, "setText"):
                        self.select_all_btn.setText("☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            elif selected_items_count == total_items and total_items > 0:
                self.all_selected = True
                try:
                    if hasattr(self.select_all_btn, "setText"):
                        self.select_all_btn.setText("❌ 取消全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
        except Exception as e:
            logger.error(f"處理選擇變化失敗: {e}\n{traceback.format_exc()}")

    def _is_local_mods_scope_current(self, request_token: int, server_path_key: str | None) -> bool:
        current_token = int(getattr(self, "_local_mods_load_token", 0))
        if request_token != current_token:
            return False
        return self._get_current_server_path_key(getattr(self, "current_server", None)) == server_path_key

    def _set_bulk_controls_enabled(self, enabled: bool) -> None:
        """設定批量操作控制元件的啟用/停用狀態"""
        try:
            if hasattr(self, "select_all_btn") and self.select_all_btn:
                self.select_all_btn.setEnabled(enabled)
        except Exception as e:
            logger.debug(f"設定全選按鈕狀態失敗: {e}")
        try:
            if hasattr(self, "batch_toggle_btn") and self.batch_toggle_btn:
                self.batch_toggle_btn.setEnabled(enabled)
        except Exception as e:
            logger.debug(f"設定批量切換按鈕狀態失敗: {e}")

    def _run_debounced_local_filter_refresh(self) -> None:
        self._local_filter_job = None
        self.refresh_local_list()


__all__ = ["LocalModListPresenter"]
