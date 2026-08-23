"""線上瀏覽與安裝佇列流程"""

from __future__ import annotations

import re
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTreeWidgetItem,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SubtitleLabel,
    TextEdit,
    TreeWidget,
)

from src.core import (
    analyze_mod_version_compatibility,
    get_mod_versions,
    resolve_modrinth_project_names,
    search_mods_online,
)
from src.models import OnlineBrowseRequest, PendingOnlineInstall
from src.ui import (
    HostBound,
    ModalMSFluentWindow,
    build_server_install_blocking_reason,
    format_online_version_report,
    get_online_version_status_text,
    resolve_online_mod_project_page_url,
    sort_online_versions_for_server,
)
from src.ui import mod_management_logger as logger
from src.utils import (
    SUPPORTED_MODRINTH_UPDATE_LOADERS,
    AppException,
    Sizes,
    UIUtils,
    UIWorkScope,
    apply_table_header_style,
)


class ModManagementQueueOps(HostBound):
    """封裝線上瀏覽、搜尋與安裝佇列互動流程"""

    mod_session: Any
    mod_manager: Any
    parent: Any
    ui_queue: Any
    scope: UIWorkScope
    browse_tree: Any
    browse_filter_label: Any
    browse_results_label: Any
    browse_sort_options: Any
    browse_sort_var: Any
    online_search_filter: Any
    notebook: Any
    update_status: Callable[..., Any]
    update_status_safe: Callable[..., Any]
    refresh_browse_list: Callable[..., Any]
    _clear_online_mods: Callable[..., Any]
    _build_online_browse_key: Callable[..., str]
    _format_online_environment_text: Callable[..., str]
    show_online_install_queue: Callable[..., Any]
    _open_project_page: Callable[..., Any]

    def _get_supported_online_loader(self) -> tuple[str | None, str | None]:
        current_server = self.mod_session.server
        if not current_server:
            return (None, "請先選擇伺服器後再使用線上模組功能")
        raw_loader = str(getattr(current_server, "loader_type", "") or "").strip()
        normalized_loader = raw_loader.lower()
        if normalized_loader not in SUPPORTED_MODRINTH_UPDATE_LOADERS:
            return (
                None,
                f"線上模組功能目前僅支援 Fabric / Forge / Quilt / NeoForge，當前伺服器載入器為：{raw_loader or '未設定'}",
            )
        return (normalized_loader, None)

    def _refresh_online_queue_button(self) -> None:
        button = getattr(self, "online_queue_button", None)
        if button:
            button.setText(f"🧺 安裝清單 ({len(self.mod_session.pending_online_installs)})")

    def _add_pending_online_install(self, pending: PendingOnlineInstall) -> bool:
        blocking_reason = build_server_install_blocking_reason(pending.server_side)
        if blocking_reason:
            logger.info("拒絕加入安裝清單: %s", blocking_reason)
            UIUtils.show_message("無法加入安裝清單", blocking_reason, self.parent, message_level="warning")
            return False
        self.mod_session.add_pending_install(pending)
        self._refresh_online_queue_button()
        self.update_status_safe(
            f"已加入安裝清單：{pending.project_name} ({getattr(pending.version, 'display_name', '未知版本')})"
        )
        return True

    def _install_online_version(
        self,
        mod: Any,
        versions: list[Any],
        version_tree: TreeWidget,
        dialog: Any,
        version_reports: list[Any] | None = None,
    ) -> None:
        selected_items = version_tree.selectedItems()
        if not selected_items:
            UIUtils.show_message("警告", "請先選擇要安裝的版本", dialog, message_level="warning")
            return
        selected_index = version_tree.indexOfTopLevelItem(selected_items[0])
        version = versions[selected_index]
        report = version_reports[selected_index] if version_reports and selected_index < len(version_reports) else None
        if report is not None and not getattr(report, "compatible", True):
            UIUtils.show_message(
                "版本不相容",
                format_online_version_report(version, report),
                dialog,
                message_level="error",
            )
            return
        file_info = getattr(version, "primary_file", None)
        if not file_info:
            UIUtils.show_message("錯誤", "此版本沒有可下載的 JAR 檔案", dialog, message_level="error")
            return
        download_url = str(file_info.get("url", "") or "")
        filename = str(file_info.get("filename", "") or "")
        if not download_url or not filename:
            UIUtils.show_message("錯誤", "無法取得下載連結或檔名", dialog, message_level="error")
            return
        if self._add_pending_online_install(
            PendingOnlineInstall(
                project_id=str(getattr(mod, "project_id", "") or "").strip(),
                project_name=str(getattr(mod, "name", "未知模組") or "未知模組").strip(),
                version=version,
                report=report,
                homepage_url=str(getattr(mod, "homepage_url", "") or "").strip(),
                source_url=str(getattr(mod, "url", "") or "").strip(),
                server_side=str(getattr(mod, "server_side", "") or "").strip(),
                client_side=str(getattr(mod, "client_side", "") or "").strip(),
            )
        ):
            if hasattr(dialog, "accept"):
                dialog.accept()
            elif hasattr(dialog, "close"):
                dialog.close()

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
        if self.browse_tree is None:
            return
        if hasattr(event, "x"):
            item = self.browse_tree.itemAt(event)
            if item is not None:
                self.browse_tree.setCurrentItem(item)
                item.setSelected(True)
        has_selection, _, _ = self._get_selected_online_mod_context()
        if not has_selection:
            return

        menu = RoundMenu(parent=self.browse_tree)

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

        menu.exec(QCursor.pos())

    def install_online_mod(self, _event=None) -> None:
        """
        取得模組版本列表並讓使用者選擇要安裝的版本

        Args:
            _event: 事件繫結傳入的事件物件，未使用
        """
        manager = self.mod_manager
        if not self.mod_session.server or not manager:
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

        session = self.mod_session
        scope = session.begin_version_load()

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
                sorted_versions, sorted_reports = sort_online_versions_for_server(versions, version_reports)
                versions = sorted_versions
                version_reports = sorted_reports or []

                if not session.is_scope_current(scope):
                    return

                def open_dialog() -> None:
                    if not session.is_scope_current(scope):
                        return
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
                if not session.is_scope_current(scope):
                    return
                logger.error(f"取得模組版本失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"取得模組版本失敗: {e}")

        self.scope.submit(load_versions_task, key="online_versions", replace=True)

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
        url = resolve_online_mod_project_page_url(mod)
        if url:
            UIUtils.open_external(url)

    def _get_current_modrinth_context(self) -> tuple[str | None, str | None, str | None]:
        """依目前選取伺服器取得 Minecraft、loader 與 loader 版本資訊"""
        current_server = self.mod_session.server
        if not current_server:
            return (None, None, None)
        minecraft_version = str(getattr(current_server, "minecraft_version", "") or "").strip() or None
        loader_type = str(getattr(current_server, "loader_type", "") or "").strip() or None
        loader_version = str(getattr(current_server, "loader_version", "") or "").strip() or None
        return (minecraft_version, loader_type, loader_version)

    def _get_current_modrinth_filters(self) -> tuple[str | None, str | None]:
        """依目前選取伺服器取得 Minecraft 版本與 loader 過濾條件"""
        minecraft_version, loader_type, _ = self._get_current_modrinth_context()
        return (minecraft_version, loader_type)

    def _get_online_filter_hint_text(self) -> str:
        """建立線上模組瀏覽/搜尋提示文字"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.mod_session.server:
            return "請先選擇伺服器並輸入關鍵字後搜尋；僅支援 Fabric / Forge / Quilt / NeoForge"
        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)
        hint = "條件：" + " / ".join(info_parts)
        if not loader_type or loader_type.lower() not in SUPPORTED_MODRINTH_UPDATE_LOADERS:
            return hint + "｜僅支援 Fabric / Forge / Quilt / NeoForge"
        return hint + "｜請輸入關鍵字後搜尋"

    def _get_online_version_dialog_hint_text(self) -> str:
        """建立版本選擇視窗的伺服器條件摘要"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.mod_session.server:
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
        item = selected_items[0]
        row = self.browse_tree.indexOfTopLevelItem(item)
        project_id = ""
        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, (tuple, list)):
                project_id = str(data[0] or "").strip()
            elif data:
                project_id = str(data).strip()

        mod = self.mod_session.online_mod_by_project_id(project_id)
        if mod is None:
            mod = self.mod_session.online_mod_at(row)
            if mod is not None and not project_id:
                project_id = str(getattr(mod, "project_id", "") or "").strip()
        return (True, project_id, mod)

    def _build_online_results_summary_text(self) -> str:
        """建立瀏覽/搜尋結果摘要，說明目前條件與結果數量"""
        query = self._get_online_query_text()
        mode_text = "請輸入關鍵字搜尋" if not query else f"搜尋 {query}"
        sort_text = self._get_online_sort_label()
        result_count = len(self.mod_session.online_mods)
        return f"{mode_text}｜{result_count} 筆｜排序 {sort_text}"

    def _refresh_online_results_summary(self) -> None:
        """更新瀏覽結果摘要列"""
        if self.browse_results_label:
            self.browse_results_label.setText(self._build_online_results_summary_text())

    def _get_online_query_text(self) -> str:
        """取得目前線上模組輸入框文字"""
        entry = getattr(self, "browse_search_entry", None)
        if entry is not None:
            return self.online_search_filter.normalize(entry.text())
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
            return self.notebook.currentIndex() == 1
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
        snapshot = self.mod_session.snapshot()
        if not force and request == snapshot.latest_online_request and snapshot.online_mods:
            return
        session = self.mod_session
        scope = session.begin_online_search(request)

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
                if not session.accept_online_results(scope, request, mods):
                    return
                online_mod_by_row_key: dict[str, Any] = {}
                for mod in mods:
                    row_key = self._build_online_browse_key(mod)
                    if row_key:
                        online_mod_by_row_key[row_key] = mod
                self._online_mod_by_row_key = online_mod_by_row_key
                self.ui_queue.put(self.refresh_browse_list)
                self.update_status_safe(f"找到 {len(mods)} 個線上模組")
            except AppException as e:
                if not session.is_scope_current(scope):
                    return
                logger.warning(f"搜尋線上模組失敗（可恢復）: {e}")
                self.update_status_safe(f"搜尋線上模組失敗: {e}")
                self.ui_queue.put(
                    lambda err=e: UIUtils.show_message(
                        "搜尋失敗", f"搜尋線上模組失敗: {err}", self.parent, message_level="error"
                    )
                )
            except Exception as e:
                if not session.is_scope_current(scope):
                    return
                logger.error(f"搜尋線上模組失敗: 未知錯誤\n{traceback.format_exc()}")
                self.update_status_safe("搜尋線上模組失敗：內部錯誤")
                self.ui_queue.put(
                    lambda err=e: UIUtils.show_message(
                        "搜尋失敗", f"搜尋線上模組時發生未知錯誤:\n{err}", self.parent, message_level="error"
                    )
                )

        self.scope.submit(search_task, key="online_search", replace=True)

    def _show_version_install_dialog(
        self, mod: Any, versions: list[Any], version_reports: list[Any] | None = None
    ) -> None:
        """顯示版本選擇對話框"""
        dialog = ModalMSFluentWindow(self.parent, show_buttons=False)
        dialog.setWindowTitle(f"安裝模組 - {mod.name}")
        dialog.resize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
        dialog.setMinimumSize(750, 645)

        title = SubtitleLabel(f"選擇要安裝的版本：{mod.name}", dialog.widget)
        dialog.viewLayout.addWidget(title)

        filter_label = BodyLabel(self._get_online_version_dialog_hint_text(), dialog.widget)
        filter_label.setWordWrap(True)
        dialog.viewLayout.addWidget(filter_label)

        version_tree = TreeWidget(dialog.widget)
        version_tree.setColumnCount(6)
        version_tree.setHeaderLabels(["版本", "類型", "Minecraft", "Loader", "狀態", "發布時間"])
        apply_table_header_style(version_tree)
        version_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        version_tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        version_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        version_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        version_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        dialog.viewLayout.addWidget(version_tree, 1)

        for index, version in enumerate(versions):
            published = str(getattr(version, "date_published", "") or "")
            report = None
            if version_reports and index < len(version_reports):
                report = version_reports[index]
            status_text = get_online_version_status_text(report)
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

        summary_label = SubtitleLabel("版本分析", dialog.widget)
        dialog.viewLayout.addWidget(summary_label)

        summary_box = TextEdit(dialog.widget)
        summary_box.setReadOnly(True)
        summary_box.setFixedHeight(Sizes.SERVER_TREE_COL_LOADER)
        dialog.viewLayout.addWidget(summary_box)

        button_frame = QFrame(dialog.widget)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        dialog.viewLayout.addWidget(button_frame)

        install_button = PrimaryPushButton("➕ 加入安裝清單", button_frame)
        install_button.clicked.connect(
            lambda _checked=False: self._install_online_version(mod, versions, version_tree, dialog, version_reports)
        )
        button_layout.addWidget(install_button)

        open_button = PushButton("🧺 查看清單", button_frame)
        open_button.clicked.connect(self.show_online_install_queue)
        button_layout.addWidget(open_button)

        project_page_url = resolve_online_mod_project_page_url(mod)
        project_page_button = PushButton("🌐 專案頁面", button_frame)
        project_page_button.clicked.connect(lambda _checked=False: self._open_project_page(project_page_url, dialog))
        project_page_button.setEnabled(bool(project_page_url))
        button_layout.addWidget(project_page_button)

        button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        close_button = PushButton("關閉", button_frame)
        if hasattr(dialog, "reject"):
            close_button.clicked.connect(dialog.reject)
        elif hasattr(dialog, "close"):
            close_button.clicked.connect(dialog.close)
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
                    summary_box.insertPlainText(format_online_version_report(selected_version, report))
                elif hasattr(summary_box, "setText"):
                    summary_box.setText(format_online_version_report(selected_version, report))
                summary_box.setReadOnly(True)

            install_button.setEnabled(report is None or getattr(report, "compatible", True))

        version_tree.itemSelectionChanged.connect(refresh_version_report)
        refresh_version_report()
        dialog.exec()


__all__ = ["ModManagementQueueOps"]
