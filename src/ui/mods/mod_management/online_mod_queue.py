"""線上瀏覽與安裝佇列流程"""

from __future__ import annotations

import queue
import re
import traceback
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import Action, PrimaryPushButton, PushButton, RoundMenu, TreeWidget

from ....core import AppException
from ....models import OnlineBrowseRequest, PendingOnlineInstall
from ....utils import (
    Sizes,
    Spacing,
    TaskUtils,
    UIUtils,
)
from ... import (
    analyze_mod_version_compatibility,
    get_mod_versions,
    resolve_modrinth_project_names,
    search_mods_online,
)
from .constants import SUPPORTED_ONLINE_MOD_LOADERS, logger
from .install_review_dialog_builder import InstallReviewDialogBuilder


class ModManagementRuntimeBase:
    """為拆分後的 mixin 提供共同宿主屬性型別"""

    parent: Any
    current_server: Any | None
    mod_manager: Any | None
    notebook: Any | None
    browse_tree: TreeWidget | None
    browse_filter_label: Any | None
    browse_results_label: Any | None
    browse_sort_var: Any
    browse_sort_options: dict[str, str]
    local_tree: TreeWidget | None
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
        """讓共同宿主 mixin 的交叉方法在型別檢查時保持可見"""
        raise AttributeError(_name)


class ModManagementQueueMixin(ModManagementRuntimeBase):
    """封裝線上瀏覽、搜尋與安裝佇列互動流程"""

    @staticmethod
    def _format_single_line_text(value: Any) -> str:
        """將多行或多空白文字正規化為單行"""
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def on_online_browse_filters_changed(self, _value: str) -> None:
        """
        線上瀏覽排序變更時立即刷新清單

        Args:
            _value: 下拉選單回傳的目前值
        """
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()
        self._load_online_mods(force=True, show_warning=False)

    def search_online_mods(self, _event=None) -> None:
        """
        載入 Modrinth 線上模組並觸發搜尋

        Args:
            _event: 事件繫結傳入的事件物件，未使用
        """
        self._load_online_mods(force=True, show_warning=True)

    def show_browse_context_menu(self, event) -> None:
        """
        顯示線上模組右鍵選單

        Args:
            event: 觸發選單的滑鼠事件
        """
        has_selection, _, _ = self._get_selected_online_mod_context()
        if not has_selection:
            return
        menu = RoundMenu(parent=self.parent)

        action_install = Action("⬇️ 安裝模組", menu)
        action_install.triggered.connect(self.install_online_mod)
        menu.addAction(action_install)

        menu.addSeparator()

        action_copy = Action("📋 複製模組資訊", menu)
        action_copy.triggered.connect(self.copy_online_mod_info)
        menu.addAction(action_copy)

        action_web = Action("🌐 開啟模組頁面", menu)
        action_web.triggered.connect(self.open_mod_webpage)
        menu.addAction(action_web)

        if hasattr(event, "globalPos"):
            menu.exec(event.globalPos())
        else:
            menu.exec(QCursor.pos())

    def install_online_mod(self, _event=None) -> None:
        """
        取得模組版本列表並讓使用者選擇要安裝的版本

        Args:
            _event: 事件繫結傳入的事件物件，未使用
        """
        manager = self.mod_manager
        if not self.current_server or not manager:
            UIUtils.show_message("警告", "請先選擇伺服器後再安裝模組", self.parent, message_level="warning")
            return
        has_selection, _, selected_mod = self._get_selected_online_mod_context()
        if not has_selection:
            UIUtils.show_message("警告", "請先從線上列表選取模組", self.parent, message_level="warning")
            return
        if not selected_mod:
            UIUtils.show_message("錯誤", "找不到選取的線上模組資料", self.parent, message_level="error")
            return
        minecraft_version, _, loader_version = self._get_current_modrinth_context()
        loader_type, warning_message = self._get_supported_online_loader()
        if warning_message:
            UIUtils.show_message("目前不支援", warning_message, self.parent, message_level="warning")
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
                        UIUtils.show_message(
                            "找不到版本",
                            f"{selected_mod.name} 目前查無可下載版本",
                            self.parent,
                            message_level="warning",
                        )
                        return
                    self._show_version_install_dialog(selected_mod, versions, version_reports)

                self.ui_queue.put(open_dialog)
                self.update_status_safe(f"已載入 {selected_mod.name} 的 {len(versions)} 個版本")
            except Exception as e:
                logger.error(f"取得模組版本失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"取得模組版本失敗: {e}")

        TaskUtils.run_async(load_versions_task)

    def copy_online_mod_info(self) -> None:
        """複製線上模組資訊"""
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
            clipboard = QApplication.clipboard()
            clipboard.setText(info)
            if hasattr(QApplication, "processEvents"):
                QApplication.processEvents()
        except Exception as e:
            logger.error(f"複製線上模組資訊失敗: {e}")
            UIUtils.show_message("複製失敗", f"無法將模組資訊複製到剪貼簿：{e}", self.parent, message_level="error")
            return
        self.update_status("線上模組資訊已複製到剪貼簿")

    def open_mod_webpage(self) -> None:
        """開啟選取模組的 Modrinth 頁面"""
        _, _, mod = self._get_selected_online_mod_context()
        if not mod:
            return
        url = self._resolve_online_mod_project_page_url(mod)
        if url:
            UIUtils.open_external(url)

    def _get_current_modrinth_context(self) -> tuple[str | None, str | None, str | None]:
        """依目前選取伺服器取得 Minecraft、loader 與 loader 版本資訊"""
        if not self.current_server:
            return (None, None, None)
        minecraft_version = str(getattr(self.current_server, "minecraft_version", "") or "").strip() or None
        loader_type = str(getattr(self.current_server, "loader_type", "") or "").strip() or None
        loader_version = str(getattr(self.current_server, "loader_version", "") or "").strip() or None
        return (minecraft_version, loader_type, loader_version)

    def _get_current_modrinth_filters(self) -> tuple[str | None, str | None]:
        """依目前選取伺服器取得 Minecraft 版本與 loader 過濾條件"""
        minecraft_version, loader_type, _ = self._get_current_modrinth_context()
        return (minecraft_version, loader_type)

    def _get_online_filter_hint_text(self) -> str:
        """建立線上模組瀏覽/搜尋提示文字"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.current_server:
            return "請先選擇伺服器並輸入關鍵字後搜尋；僅支援 Fabric / Forge / Quilt / NeoForge"
        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)
        hint = "條件：" + " / ".join(info_parts)
        if not loader_type or loader_type.lower() not in SUPPORTED_ONLINE_MOD_LOADERS:
            return hint + "｜僅支援 Fabric / Forge / Quilt / NeoForge"
        return hint + "｜請輸入關鍵字後搜尋"

    def _get_online_version_dialog_hint_text(self) -> str:
        """建立版本選擇視窗的伺服器條件摘要"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.current_server:
            return "會依目前伺服器條件自動分析版本相容性"
        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)
        return "相容性條件：" + " / ".join(info_parts)

    def _refresh_online_filter_hint(self) -> None:
        """更新線上模組搜尋提示"""
        if self.browse_filter_label:
            self.browse_filter_label.setText(self._get_online_filter_hint_text())

    def _get_online_sort_label(self) -> str:
        """取得目前線上瀏覽使用的排序顯示文字"""
        if not hasattr(self, "browse_sort_var"):
            return "相關性"
        return str(self.browse_sort_var.get() or "相關性").strip() or "相關性"

    def _format_online_result_description(self, mod: Any) -> str:
        """格式化瀏覽列表描述欄位"""
        return self._format_single_line_text(getattr(mod, "description", ""))

    def _get_selected_online_mod_context(self) -> tuple[bool, str, Any | None]:
        """取得目前線上模組選取狀態、project_id 與模組物件"""
        if not self.browse_tree:
            return (False, "", None)
        selected_items = self.browse_tree.selectedItems()
        if not selected_items:
            return (False, "", None)
        row = selected_items[0].row()
        item = self.browse_tree.item(row, 0)
        project_id = ""
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                project_id = str(data)

        mod = self._online_mod_index.get(project_id)
        if mod is None:
            mod = self._online_mod_by_row_key.get(str(row))
            if mod is not None and not project_id:
                project_id = str(getattr(mod, "project_id", "") or "").strip()
        return (True, project_id, mod)

    def _build_online_results_summary_text(self) -> str:
        """建立瀏覽/搜尋結果摘要，說明目前條件與結果數量"""
        query = self._get_online_query_text()
        mode_text = "請輸入關鍵字搜尋" if not query else f"搜尋 {query}"
        sort_text = self._get_online_sort_label()
        result_count = len(self.online_mods)
        return f"{mode_text}｜{result_count} 筆｜排序 {sort_text}"

    def _refresh_online_results_summary(self) -> None:
        """更新瀏覽結果摘要列"""
        if self.browse_results_label:
            self.browse_results_label.setText(self._build_online_results_summary_text())

    def _get_online_query_text(self) -> str:
        """取得目前線上模組輸入框文字"""
        if not hasattr(self, "search_var"):
            return ""
        query = self.search_var.get() or ""
        search_filter = getattr(self, "online_search_filter", None)
        if search_filter is not None:
            return search_filter.normalize(query)
        return str(query).strip()

    def _build_online_browse_request(self) -> tuple[OnlineBrowseRequest | None, str | None]:
        """建立目前的線上瀏覽/搜尋請求"""
        minecraft_version, _ = self._get_current_modrinth_filters()
        loader_type, warning_message = self._get_supported_online_loader()
        if warning_message or not loader_type:
            return (None, warning_message)
        query = self._get_online_query_text()
        if not query:
            return (None, "請先輸入關鍵字再搜尋模組")
        sort_by = self.browse_sort_options.get(self.browse_sort_var.get(), "relevance")
        return (
            OnlineBrowseRequest(
                query=query, minecraft_version=minecraft_version, loader_type=loader_type, sort_by=sort_by
            ),
            None,
        )

    def _is_browse_tab_active(self) -> bool:
        """判斷目前是否正在顯示線上瀏覽頁"""
        if not self.notebook:
            return False
        try:
            return self.notebook.index(self.notebook.select()) == 1
        except Exception:
            return False

    def _load_online_mods(self, *, force: bool = False, show_warning: bool = True) -> None:
        """依目前條件載入線上模組（需輸入關鍵字）"""
        request, warning_message = self._build_online_browse_request()
        if request is None:
            if show_warning:
                UIUtils.show_message("目前不支援", warning_message, self.parent, message_level="warning")
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
                self.ui_queue.put(
                    lambda err=e: UIUtils.show_message(
                        "搜尋失敗", f"搜尋線上模組失敗: {err}", self.parent, message_level="error"
                    )
                )
            except Exception as e:
                logger.error(f"搜尋線上模組失敗: 未知錯誤\n{traceback.format_exc()}")
                self.update_status_safe("搜尋線上模組失敗：內部錯誤")
                self.ui_queue.put(
                    lambda err=e: UIUtils.show_message(
                        "搜尋失敗", f"搜尋線上模組時發生未知錯誤:\n{err}", self.parent, message_level="error"
                    )
                )

        TaskUtils.run_async(search_task)

    def _show_version_install_dialog(
        self, mod: Any, versions: list[Any], version_reports: list[Any] | None = None
    ) -> None:
        """顯示版本選擇對話框"""
        dialog = QDialog(self.parent)
        dialog.setWindowTitle(f"安裝模組 - {mod.name}")
        dialog.resize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
        dialog.setMinimumSize(750, 645)
        dialog.setModal(True)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        main_frame = QFrame(dialog)
        main_layout = QVBoxLayout(main_frame)
        main_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.addWidget(main_frame)

        title = QLabel(f"選擇要安裝的版本：{mod.name}", main_frame)
        main_layout.addWidget(title)

        filter_label = QLabel(self._get_online_version_dialog_hint_text(), main_frame)
        filter_label.setWordWrap(True)
        main_layout.addWidget(filter_label)

        version_tree = TreeWidget(main_frame)
        version_tree.setColumnCount(6)
        version_tree.setHeaderLabels(["版本", "類型", "Minecraft", "Loader", "狀態", "發布時間"])
        version_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        version_tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        version_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        version_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        version_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        main_layout.addWidget(version_tree, 1)

        for index, version in enumerate(versions):
            published = str(getattr(version, "date_published", "") or "")
            report = None
            if version_reports and index < len(version_reports):
                report = version_reports[index]
            status_text = self._get_online_version_status_text(report)
            v_type = getattr(version, "version_type", "") or ""
            type_display = "正式版" if v_type == "release" else ("測試版" if "beta" in v_type else v_type.capitalize())

            item = QTreeWidgetItem(
                [
                    str(getattr(version, "display_name", "未知版本")),
                    type_display,
                    ", ".join(getattr(version, "game_versions", []) or []) or "-",
                    ", ".join(getattr(version, "loaders", []) or []) or "-",
                    status_text,
                    published.replace("T", " ").replace("Z", "")[:16] if published else "-",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, version)
            version_tree.addTopLevelItem(item)

        if versions and version_tree.topLevelItemCount() > 0:
            item = version_tree.topLevelItem(0)
            item.setSelected(True)

        summary_label = QLabel("版本分析", main_frame)
        main_layout.addWidget(summary_label)

        summary_box = InstallReviewDialogBuilder.create_review_summary_box(
            main_frame, height=Sizes.SERVER_TREE_COL_LOADER
        )
        main_layout.addWidget(summary_box)

        button_frame = QFrame(main_frame)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(button_frame)

        install_button = PrimaryPushButton("➕ 加入安裝清單", button_frame)
        install_button.clicked.connect(
            lambda: self._install_online_version(mod, versions, version_tree, dialog, version_reports)
        )
        button_layout.addWidget(install_button)

        open_button = PushButton("🧺 查看清單", button_frame)
        open_button.clicked.connect(self.show_online_install_queue)
        button_layout.addWidget(open_button)

        project_page_url = self._resolve_online_mod_project_page_url(mod)
        project_page_button = PushButton("🌐 專案頁面", button_frame)
        project_page_button.clicked.connect(lambda: self._open_project_page(project_page_url, dialog))
        project_page_button.setEnabled(bool(project_page_url))
        button_layout.addWidget(project_page_button)

        button_layout.addStretch(1)

        close_button = PushButton("關閉", button_frame)
        if hasattr(dialog, "reject"):
            close_button.clicked.connect(dialog.reject)
        elif hasattr(dialog, "destroy"):
            close_button.clicked.connect(dialog.destroy)
        button_layout.addWidget(close_button)

        def refresh_version_report() -> None:
            selected_items = version_tree.selectedItems()
            if not selected_items:
                return
            selected_row = version_tree.indexOfTopLevelItem(selected_items[0])
            if selected_row < 0 or selected_row >= len(versions):
                return
            selected_version = versions[selected_row]
            report = None
            if version_reports and selected_row < len(version_reports):
                report = version_reports[selected_row]

            if hasattr(summary_box, "setReadOnly"):
                summary_box.setReadOnly(False)
                if hasattr(summary_box, "clear"):
                    summary_box.clear()
                if hasattr(summary_box, "insertPlainText"):
                    summary_box.insertPlainText(self._format_online_version_report(selected_version, report))
                elif hasattr(summary_box, "setText"):
                    summary_box.setText(self._format_online_version_report(selected_version, report))
                summary_box.setReadOnly(True)

            install_button.setEnabled(report is None or getattr(report, "compatible", True))

        version_tree.itemSelectionChanged.connect(refresh_version_report)
        refresh_version_report()
        dialog.show()


__all__ = ["ModManagementQueueMixin"]
