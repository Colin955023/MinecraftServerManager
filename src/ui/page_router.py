"""
頁面路由控制器
負責管理主視窗的頁面切換與導覽列狀態。
"""

from typing import TYPE_CHECKING

from ..utils import TaskUtils, UIUtils
from ..utils.ui_support import qt_widgets as qt

if TYPE_CHECKING:
    from .main_window import MainWindow


class PageRouter:
    def __init__(self, main_window: MainWindow):
        self.main_window = main_window

    def set_active_nav_button(self, key: str) -> None:
        """更新側邊欄導航按鈕的選取狀態"""
        if getattr(self.main_window, "active_nav_key", None) == key:
            return

        self.main_window.active_nav_key = key

        for k, btn in self.main_window.nav_buttons.items():
            if k == key:
                btn.configure(button_type="primary")
            else:
                btn.configure(button_type="secondary")

    def show_create_server(self) -> None:
        """顯示建立伺服器頁面"""
        self.set_active_nav_button("create")
        self.main_window._ensure_manage_server_frame()
        self.show_page_frame(self.main_window.create_server_frame)

        if hasattr(self.main_window.create_server_frame, "reset_form"):
            self.main_window.create_server_frame.reset_form()

    def show_manage_server(self, auto_select: str | None = None) -> None:
        """顯示管理伺服器頁面"""
        self.set_active_nav_button("manage")
        self.main_window._ensure_manage_server_frame()
        self.show_page_frame(self.main_window.manage_server_frame)

        if auto_select:
            # 延遲選取以確保 UI 已經完全繪製
            TaskUtils.run_async(
                lambda: TaskUtils.run_in_main_thread(lambda: self._refresh_and_optionally_select(auto_select))
            )

    def _refresh_and_optionally_select(self, auto_select: str) -> None:
        if not hasattr(self.main_window, "manage_server_frame") or not self.main_window.manage_server_frame:
            return

        try:
            self.main_window.manage_server_frame.refresh_servers()
            # 將自動選取委託給 ManageServerFrame 自己處理
            self.main_window.manage_server_frame.select_server_by_name(auto_select)
        except Exception as e:
            UIUtils.get_logger().bind(component="PageRouter").error(f"自動選取伺服器失敗: {e}")

    def show_mod_management(self) -> None:
        """顯示模組管理頁面"""
        self.set_active_nav_button("mod")
        self.main_window._ensure_mod_management_frame()
        self.show_page_frame(self.main_window.mod_frame)

    def add_page_widget(self, frame) -> qt.Widget | None:
        """將頁面 frame 加入至 stacked widget，如果已存在則不重複加入"""
        if not self.main_window.content_frame:
            return None
        return self.main_window.content_frame.add_widget(frame)

    def show_page_frame(self, frame) -> None:
        """切換 StackedWidget 至指定的頁面"""
        if not self.main_window.content_frame:
            return

        widget = self.add_page_widget(frame)
        if widget:
            self.main_window.content_frame.set_current_widget(widget)
