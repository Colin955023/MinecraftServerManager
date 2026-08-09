"""
還原備份對話框
提供使用者從歷史備份中選擇並還原
"""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import BodyLabel, TreeWidget

from ..utils import UIUtils, run_in_background, run_on_ui_thread
from . import ModalMSFluentWindow, ProgressDialog


class RestoreBackupDialog(ModalMSFluentWindow):
    """
    還原備份對話框
    允許使用者從備份列表中選擇一個備份並將其還原至伺服器
    """

    def __init__(self, parent: Any, server_name: str, server_backup, server_crud):
        super().__init__(parent)
        self.server_name = server_name
        self.server_backup = server_backup
        self.server_crud = server_crud
        self.setWindowTitle(f"還原 {server_name} 的備份")

    def setup_ui(self):
        """建立對話框的 UI 佈局，包含備份列表樹狀視圖與操作按鈕"""
        self.widget.setMinimumSize(500, 400)

        label = BodyLabel("請選擇要還原的備份：\n(警告：這將會覆蓋伺服器目前的資料)", self.widget)
        self.viewLayout.addWidget(label)

        self.tree = TreeWidget(self.widget)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["時間", "檔案名稱", "大小 (MB)"])
        self.viewLayout.addWidget(self.tree)

        self._load_backups()

        self.cancelButton.clicked.disconnect()
        self.yesButton.clicked.disconnect()

        self.cancelButton.setText("取消")
        self.cancelButton.clicked.connect(self.reject)

        self.yesButton.setText("還原")
        self.yesButton.clicked.connect(self._on_restore_clicked)

    def exec_dialog(self) -> bool:
        """
        顯示對話框並等待使用者回應

        Returns:
            bool: 如果使用者選擇還原並成功執行，返回 True；否則返回 False
        """
        self.setup_ui()
        return self.exec()

    def _load_backups(self):
        config = self.server_crud.servers.get(self.server_name)
        if not config:
            return
        backups = self.server_backup.list_backups(self.server_name)
        self.backup_list = backups
        for i, b in enumerate(backups):
            item = QtWidgets.QTreeWidgetItem([b["readable_time"], b["filename"], f"{b['size_mb']:.2f}"])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, i)
            self.tree.addTopLevelItem(item)

    def _on_restore_clicked(self):
        """處理還原按鈕點擊事件，驗證選擇並執行還原操作"""
        selected = self.tree.selectedItems()
        if not selected:
            UIUtils.show_message("提示", "請先選擇一個備份", self, message_level="warning")
            return

        idx = selected[0].data(0, QtCore.Qt.ItemDataRole.UserRole)
        backup = self.backup_list[idx]
        filename = backup["filename"]
        filepath = backup["path"]

        if not UIUtils.ask_yes_no_cancel(
            "確認還原",
            f"您確定要還原備份 {filename} 嗎？\n伺服器目前的資料將會遺失！",
            self,
            show_cancel=False,
        ):
            return

        dialog = ProgressDialog(self, title="還原備份", show_cancel=False)
        dialog.update_progress(0, "準備還原...")

        def _restore_task() -> bool:
            return self.server_backup.restore_backup(
                self.server_name, filepath, progress_callback=dialog.update_progress
            )

        def _on_done(success: bool) -> None:
            def _ui_done():
                dialog.close()
                if success:
                    UIUtils.show_message("成功", "備份還原成功！", self, message_level="info")
                    self.accept()
                else:
                    UIUtils.show_message("失敗", "備份還原失敗，請查看日誌", self, message_level="error")

            run_on_ui_thread(_ui_done)

        run_in_background(_restore_task, callback=_on_done)
        dialog.exec_dialog()
