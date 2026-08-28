"""Mod Review 的 Qt adapter"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTreeWidgetItem
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton

from src.models import LocalModUpdatePlan
from src.utils import (
    Colors,
    Sizes,
    Spacing,
    UIUtils,
)

from .constants import logger
from .install_review_dialog_builder import InstallReviewDialogBuilder
from .review_contracts import ReviewViewSnapshot
from .review_workflow import (
    LocalReviewSession,
    ModReviewWorkflow,
    OnlineReviewSession,
)


def _selected_node_ids(tree: Any) -> set[str]:
    selected_ids: set[str] = set()
    for item in list(tree.selectedItems() or []):
        node_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if node_id:
            selected_ids.add(node_id)
    return selected_ids


def _selected_root_key(tree: Any, snapshot: ReviewViewSnapshot) -> str:
    node_root_map = {node.node_id: node.root_key for node in snapshot.task_nodes}
    for node_id in _selected_node_ids(tree):
        root_key = node_root_map.get(node_id)
        if root_key:
            return root_key
    return ""


if TYPE_CHECKING:
    from .frame import ModManagementFrame


class ModManagementReviewOps:
    """將 workflow snapshot 呈現在 Qt，並把 UI command 送回 session"""

    def __init__(self, controller: ModManagementFrame) -> None:
        self.controller = controller
        self._dependency_snapshot_migration_totals = {
            "checked": 0,
            "migrated": 0,
            "replayed": 0,
            "fallback_rebuild": 0,
        }
        self.install_review_dialog_builder: InstallReviewDialogBuilder | None = None

    def _create_review_workflow(self) -> ModReviewWorkflow | None:
        manager = self.controller.mod_manager
        current_server = self.controller.mod_session.server
        if not current_server or not manager:
            return None
        installed_mods = manager.get_mod_list()
        telemetry = self._dependency_snapshot_migration_totals
        return ModReviewWorkflow(
            mod_planning=self.controller.mod_planning,
            server=current_server,
            installed_mods=installed_mods,
            telemetry=telemetry,
            mod_manager=manager,
        )

    def show_online_install_queue(self, _event=None) -> None:
        """
        建立目前待安裝清單的 Review session 並顯示對話框

        Args:
            _event: Qt signal 傳入但不使用的事件值
        """
        pending_installs = self.controller.mod_session.pending_online_installs
        if not pending_installs:
            UIUtils.show_message("安裝清單", "目前安裝清單是空的", self.controller.parent, message_level="info")
            return
        workflow = self._create_review_workflow()
        if workflow is None:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.controller.parent, message_level="error")
            return
        session = workflow.start_online_session(list(pending_installs))
        self._show_online_review_dialog(session)

    def _show_online_review_dialog(self, session: OnlineReviewSession) -> None:
        snapshot = session.snapshot()
        shell = self._get_install_review_dialog_builder().create_review_dialog_shell(
            dialog_title="安裝清單 Review",
            heading="待安裝模組與依賴檢查",
            subtitle_text=snapshot.subtitle,
            summary_height=Sizes.SERVER_TREE_COL_LOADER,
            min_width=750,
            min_height=615,
        )
        dialog = shell.dialog
        shell.overview_label.setText(snapshot.overview)
        queue_banner = BodyLabel(f"安裝清單：共 {len(snapshot.roots)} 項（可安裝 {snapshot.actionable_count}）")
        layout = shell.tree_container.layout()
        if layout and hasattr(layout, "insertWidget"):
            layout.insertWidget(0, queue_banner)
        queue_tree = self._get_install_review_dialog_builder().create_review_tree(
            shell.tree_container,
            tree_heading="項目",
            column_specs=[
                ("run", "執行", Sizes.BUTTON_WIDTH_COMPACT, 45, False, "center"),
                ("source", "來源", Sizes.BUTTON_WIDTH_SMALL, 60, False, "w"),
                ("name", "名稱", Sizes.CONSOLE_PANEL_HEIGHT, 120, True, "w"),
                ("version", "版本", Sizes.DIALOG_SMALL_HEIGHT, 90, False, "w"),
                ("channel", "類型", Sizes.BUTTON_WIDTH_SMALL, 60, False, "w"),
                ("status", "狀態", Sizes.SERVER_TREE_COL_LOADER + 10, 98, False, "w"),
            ],
            tree_column_width=Sizes.BUTTON_WIDTH_SECONDARY,
            stretch_columns={"name"},
        )
        self._render_review_task_tree(queue_tree, snapshot)

        def refresh_summary(_event=None) -> None:
            root = snapshot.root(_selected_root_key(queue_tree, snapshot))
            if root:
                shell.summary_box.setPlainText(root.summary)

        def refresh_project_button(_event=None) -> None:
            root = snapshot.root(_selected_root_key(queue_tree, snapshot))
            project_button.setEnabled(bool(root and root.project_page_url))

        def open_project_page() -> None:
            root = snapshot.root(_selected_root_key(queue_tree, snapshot))
            self._open_project_page(root.project_page_url if root else "", dialog)

        def remove_selected() -> None:
            node_root_map = {node.node_id: node.root_key for node in snapshot.task_nodes}
            selected_roots = {
                node_root_map[node_id] for node_id in _selected_node_ids(queue_tree) if node_id in node_root_map
            }
            self._remove_pending_online_installs(selected_roots, dialog)

        def trigger_online_install() -> None:
            handoff = session.build_handoff()
            dialog.accept()
            self.controller.install_executor.execute_online_review(dialog, handoff)

        install_button = self._create_review_action_button(
            shell.button_frame,
            text=f"⬇️ 安裝 {snapshot.actionable_count} 個可安裝項目",
            fg_color=Colors.BUTTON_SUCCESS,
            command=trigger_online_install,
            bold=True,
        )
        install_button.setEnabled(snapshot.actionable_count > 0)
        self._create_review_action_button(shell.button_frame, text="移除選取項目", command=remove_selected)
        self._create_review_action_button(
            shell.button_frame, text="清空清單", command=lambda: self._clear_pending_online_installs(dialog)
        )
        project_button = self._append_project_and_close_actions(shell, dialog, open_project_page)
        queue_tree.itemSelectionChanged.connect(refresh_summary)
        queue_tree.itemSelectionChanged.connect(refresh_project_button)
        refresh_summary()
        refresh_project_button()
        dialog.exec()

    def _remove_pending_online_installs(self, selected_root_keys: set[str], dialog: Any) -> None:
        if not selected_root_keys:
            UIUtils.show_message("提示", "請先選擇要移除的模組項目", dialog, message_level="warning")
            return
        removed_count = self.controller.mod_session.remove_pending_review_keys(selected_root_keys)
        if removed_count <= 0:
            UIUtils.show_message("提示", "目前選取項目不可移除", dialog, message_level="warning")
            return
        self.controller.queue_ops._refresh_online_queue_button()
        dialog.close()
        if self.controller.mod_session.pending_online_installs:
            QTimer.singleShot(0, self.show_online_install_queue)

    def _clear_pending_online_installs(self, dialog: Any) -> None:
        self.controller.mod_session.clear_pending_installs()
        self.controller.queue_ops._refresh_online_queue_button()
        dialog.close()

    def _get_dialog_parent(self) -> Any:
        """安全取得 Qt 頂層視窗或 QWidget 父元件"""
        main_frame = self.controller.main_frame
        if main_frame is not None:
            return main_frame.window()
        parent = self.controller.parent
        if parent is not None:
            if hasattr(parent, "window"):
                return parent.window()
            return parent
        return None

    def check_local_mod_updates(self) -> None:
        """分析本地 Mod 更新並在結果仍屬於目前 session 時開啟 Review"""
        manager = self.controller.mod_manager
        dialog_parent = self._get_dialog_parent()
        if not self.controller.mod_session.server or not manager:
            UIUtils.show_message("警告", "請先選擇伺服器後再檢查模組更新", dialog_parent, message_level="warning")
            return
        installed_mods = manager.get_mod_list()
        if not installed_mods:
            UIUtils.show_message("提示", "目前伺服器尚未安裝任何模組", dialog_parent, message_level="info")
            return

        selected_mod_ids = self.controller.tree_sync._capture_selected_mod_ids()
        if not selected_mod_ids:
            target_mods = installed_mods
            scope_text = f"全部 {len(target_mods)} 個模組"
        else:
            target_mods = [
                mod
                for mod in installed_mods
                if mod.filename.replace(".jar.disabled", "").replace(".jar", "") in selected_mod_ids
            ]
            scope_text = f"已選取的 {len(target_mods)} 個模組"

        minecraft_version, loader_type, loader_version = self.controller.queue_ops._get_current_modrinth_context()

        def check_task() -> None:
            try:
                self.controller.update_status_safe(f"正在掃描本地模組更新與相容性 ({scope_text})...")
                self.controller.update_progress_safe(0.0)
                last_hash_progress_percent = -1

                def on_hash_progress(completed: int, total: int) -> None:
                    nonlocal last_hash_progress_percent
                    if total <= 0:
                        return
                    fraction = max(0.0, min(1.0, completed / total)) * 0.3
                    progress_percent = int(fraction * 100)
                    if progress_percent == last_hash_progress_percent:
                        return
                    last_hash_progress_percent = progress_percent
                    self.controller.update_progress_safe(fraction)
                    self.controller.update_status_safe(f"正在計算本地模組雜湊... {completed}/{total}")

                def on_stage_progress(fraction: float, status_text: str) -> None:
                    self.controller.update_progress_safe(fraction)
                    self.controller.update_status_safe(status_text)

                update_plan = self.controller.mod_planning.build_local_update_plan(
                    target_mods,
                    minecraft_version=minecraft_version,
                    loader=loader_type,
                    loader_version=loader_version,
                    hash_progress_callback=on_hash_progress,
                    provider_identity_resolver=manager.provider_identity_service.resolve_for_local_mod,
                    hash_cache_writer=lambda mod, algorithm, file_hash: manager.index_manager.cache_file_hash(
                        Path(str(getattr(mod, "file_path", "") or "")), algorithm, file_hash
                    ),
                    stage_progress_callback=on_stage_progress,
                )
                self.controller.update_progress_safe(1.0)
                self.controller.update_status_safe(
                    f"更新檢查完成：{update_plan.actionable_count} 個可更新，{len(update_plan.candidates)} 個需 Review"
                )
                self.controller.ui_queue.put(lambda: self._show_local_update_review_dialog(update_plan, scope_text))
            except Exception as e:
                logger.error(f"檢查本地模組更新失敗: {e}\n{traceback.format_exc()}")
                self.controller.update_progress_safe(0)
                self.controller.update_status_safe(f"檢查本地模組更新失敗: {e}")
                parent = self._get_dialog_parent()
                message = str(e)

                def show_error() -> None:
                    UIUtils.show_message("更新檢查失敗", message, parent, message_level="error")

                self.controller.ui_queue.put(show_error)

        self.controller.scope.submit(check_task, key="local_update_check", replace=True)

    def _get_install_review_dialog_builder(self) -> InstallReviewDialogBuilder:
        builder = self.install_review_dialog_builder
        if builder is None:
            dialog_parent = self._get_dialog_parent()
            builder = InstallReviewDialogBuilder(dialog_parent)
            self.install_review_dialog_builder = builder
        return builder

    @staticmethod
    def _open_project_page(url: str, parent: Any, *, title: str = "沒有可開啟的專案頁面") -> None:
        clean_url = str(url or "").strip()
        if not clean_url:
            UIUtils.show_message(title, "目前無法判定這個項目的專案頁面", parent, message_level="warning")
            return
        UIUtils.open_external(clean_url)

    def _create_review_action_button(
        self,
        parent: Any,
        *,
        text: str,
        fg_color: Any = None,
        _hover_color: Any = None,
        command: Callable[[], None] | None = None,
        _padx: tuple[int, int] | None = None,
        _side: str = "left",
        bold: bool = False,
    ) -> Any:
        button = PrimaryPushButton(text) if fg_color == Colors.BUTTON_SUCCESS or bold else PushButton(text)
        if command is not None:
            button.clicked.connect(command)
        layout = parent.layout()
        if layout:
            layout.addWidget(button)
        return button

    def _append_project_and_close_actions(
        self,
        shell: Any,
        dialog: Any,
        open_project_page: Callable[[], None],
    ) -> Any:
        """加入 Review 對話框共用的專案頁面與關閉操作"""
        project_button = self._create_review_action_button(
            shell.button_frame,
            text="開啟專案頁面",
            command=open_project_page,
        )
        button_layout = shell.button_frame.layout()
        if button_layout and hasattr(button_layout, "addStretch"):
            button_layout.addStretch(1)
        self._create_review_action_button(shell.button_frame, text="關閉", command=dialog.accept, _side="right")
        return project_button

    @staticmethod
    def _render_review_task_tree(tree: Any, snapshot: ReviewViewSnapshot) -> None:
        selected_key = _selected_root_key(tree, snapshot)
        tree.clear()
        group_items: dict[str, Any] = {}
        for group_key, label in snapshot.group_specs:
            if not any(node.node_kind == "root" and node.group_key == group_key for node in snapshot.task_nodes):
                continue
            item = QTreeWidgetItem(tree)
            item.setText(0, label)
            item.setData(0, Qt.ItemDataRole.UserRole, f"group::{group_key}")
            item.setExpanded(True)
            group_items[group_key] = item
        node_items: dict[str, Any] = {}
        for node in snapshot.task_nodes:
            parent_item = group_items.get(node.group_key) if node.parent_id is None else node_items.get(node.parent_id)
            item = QTreeWidgetItem(parent_item if parent_item is not None else tree)
            item.setText(0, node.title)
            for column, value in enumerate(node.values, start=1):
                item.setText(column, str(value))
            item.setData(0, Qt.ItemDataRole.UserRole, node.node_id)
            if node.node_kind in {"root", "dependency-group"}:
                item.setExpanded(True)
            node_items[node.node_id] = item
        target_key = selected_key or next(
            (node.root_key for node in snapshot.task_nodes if node.node_kind == "root"), ""
        )
        if target_key and target_key in node_items:
            node_items[target_key].setSelected(True)
            tree.scrollToItem(node_items[target_key])

    def _show_local_update_review_dialog(self, update_plan: LocalModUpdatePlan, scope_text: str) -> None:
        workflow = self._create_review_workflow()
        if workflow is None:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.controller.parent, message_level="error")
            return
        session = workflow.start_local_update_session(update_plan, scope_text)
        if session.empty:
            dialog_parent = self._get_dialog_parent()
            UIUtils.show_message("更新檢查", session.empty_message(), dialog_parent, message_level="info")
            return
        self._show_local_review_dialog(session)

    def _show_local_review_dialog(self, session: LocalReviewSession) -> None:
        snapshot = session.snapshot()
        shell = self._get_install_review_dialog_builder().create_review_dialog_shell(
            dialog_title="本地模組更新檢查",
            heading="本地模組更新與相容性 Review",
            subtitle_text=snapshot.subtitle,
            summary_height=Sizes.SERVER_TREE_COL_LOADER,
            min_width=795,
            min_height=645,
        )
        dialog = shell.dialog
        update_tree = self._get_install_review_dialog_builder().create_review_tree(
            shell.tree_container,
            tree_heading="模組",
            column_specs=[
                ("run", "套用", Spacing.XXL, 36, False, "center"),
                ("current", "目前版本", Sizes.BUTTON_WIDTH_SECONDARY, 72, False, "w"),
                ("target", "建議版本", Sizes.SERVER_TREE_COL_LOADER + 3, 90, False, "w"),
                ("source", "來源 / 識別", Sizes.SERVER_TREE_COL_LOADER + 10, 98, False, "w"),
                ("status", "檢查狀態", Sizes.INPUT_WIDTH, 180, True, "w"),
            ],
            tree_column_width=Sizes.SERVER_TREE_COL_NAME - 25,
            stretch_columns={"status"},
        )

        def refresh_summary(_event=None) -> None:
            root = snapshot.root(_selected_root_key(update_tree, snapshot))
            if root:
                shell.summary_box.setPlainText(root.summary)

        def refresh_action_button() -> None:
            update_button.setText(f"⬇️ 更新 {snapshot.selected_count} 個已選取項目")
            update_button.setEnabled(snapshot.selected_count > 0)

        def refresh_project_button(_event=None) -> None:
            root = snapshot.root(_selected_root_key(update_tree, snapshot))
            project_button.setEnabled(bool(root and root.project_page_url))

        def refresh_all() -> None:
            nonlocal snapshot
            snapshot = session.snapshot()
            shell.subtitle.setText(snapshot.subtitle)
            shell.overview_label.setText(snapshot.overview)
            self._render_review_task_tree(update_tree, snapshot)
            refresh_summary()
            refresh_action_button()
            refresh_project_button()

        def toggle_selection(selected: bool) -> None:
            if session.apply_selection(_selected_node_ids(update_tree), selected):
                refresh_all()

        def open_project_page() -> None:
            root = snapshot.root(_selected_root_key(update_tree, snapshot))
            self._open_project_page(root.project_page_url if root else "", dialog)

        def trigger_local_update() -> None:
            handoff = session.build_handoff()
            dialog.accept()
            self.controller.install_executor.execute_local_review(dialog, handoff)

        update_button = self._create_review_action_button(
            shell.button_frame,
            text="",
            command=trigger_local_update,
            bold=True,
        )
        self._create_review_action_button(
            shell.button_frame, text="納入選取項目", command=lambda: toggle_selection(True)
        )
        self._create_review_action_button(
            shell.button_frame, text="排除選取項目", command=lambda: toggle_selection(False)
        )
        project_button = self._append_project_and_close_actions(shell, dialog, open_project_page)
        update_tree.itemSelectionChanged.connect(refresh_summary)
        update_tree.itemSelectionChanged.connect(refresh_project_button)
        refresh_all()
        dialog.exec()


__all__ = ["ModManagementReviewOps"]
