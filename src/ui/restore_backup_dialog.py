"""
還原備份對話框
提供使用者從歷史備份中選擇並還原。
"""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from ..utils import UIUtils


class RestoreBackupDialog:
    def __init__(self, parent: Any, server_name: str, server_backup, server_crud):
        self.server_name = server_name
        self.server_backup = server_backup
        self.server_crud = server_crud
        self.dialog = QtWidgets.QDialog(parent)
        self.dialog.setWindowTitle(f"還原 {server_name} 的備份")

    def setup_ui(self):
        self.dialog.setFixedSize(500, 400)

        main_layout = QtWidgets.QVBoxLayout(self.dialog)

        label = QtWidgets.QLabel("請選擇要還原的備份：\n(警告：這將會覆蓋伺服器目前的資料)")
        main_layout.addWidget(label)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["時間", "檔案名稱", "大小 (MB)"])
        main_layout.addWidget(self.tree)

        self._load_backups()

        btn_frame = QtWidgets.QFrame()
        btn_layout = QtWidgets.QHBoxLayout(btn_frame)

        cancel_btn = QtWidgets.QPushButton("取消")
        cancel_btn.clicked.connect(self.dialog.reject)
        btn_layout.addWidget(cancel_btn)

        restore_btn = QtWidgets.QPushButton("還原")
        restore_btn.clicked.connect(self.on_restore)
        btn_layout.addWidget(restore_btn)

        main_layout.addWidget(btn_frame)

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

    def on_restore(self):
        selected = self.tree.selectedItems()
        if not selected:
            UIUtils.show_warning("提示", "請先選擇一個備份", self.dialog)
            return

        idx = selected[0].data(0, QtCore.Qt.ItemDataRole.UserRole)
        backup = self.backup_list[idx]

        confirm = UIUtils.ask_yes_no_cancel(
            "確認還原",
            f"您確定要還原 {backup['readable_time']} 的備份嗎？\n這將會覆蓋伺服器目前的資料！",
            self.dialog,
            show_cancel=False,
        )
        if not confirm:
            return

        success = self.server_backup.restore_backup(self.server_name, backup["path"])
        if success:
            UIUtils.show_info("還原成功", "備份已成功還原！", self.dialog)
            self.dialog.accept()
        else:
            UIUtils.show_error("還原失敗", "備份還原失敗，請查看日誌以獲取詳細資訊。", self.dialog)

    def show_modal(self):
        self.dialog.exec()
