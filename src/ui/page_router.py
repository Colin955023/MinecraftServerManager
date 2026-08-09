"""
頁面路由控制器
負責管理主視窗的頁面切換與導覽列狀態
"""

from typing import TYPE_CHECKING

from ..utils import get_logger, invoke_later

logger = get_logger().bind(component="PageRouter")

if TYPE_CHECKING:
    from .main_window import MainWindow


class PageRouter:
    """
    頁面路由控制器
    負責管理主視窗的頁面切換、導覽列狀態以及頁面切換後的初始化邏輯
    """

    def __init__(self, main_window: MainWindow):
        self.main_window = main_window

    def show_create_server(self) -> None:
        """顯示建立伺服器頁面"""
        self.main_window._ensure_manage_server_frame()
        self.show_page_frame(self.main_window.create_server_frame)

    def show_manage_server(self, auto_select: str | None = None) -> None:
        """
        顯示管理伺服器頁面

        Args:
            auto_select: 若提供伺服器名稱，則在切換頁面後嘗試自動選取該伺服器
        """
        self.main_window._ensure_manage_server_frame()
        self.show_page_frame(self.main_window.manage_server_frame)

        if auto_select:
            try:
                invoke_later(100, lambda: self._refresh_and_optionally_select(auto_select), parent=self.main_window)
            except Exception as e:
                logger.error(f"Schedule auto_select error: {e}")

    def show_mod_management(self) -> None:
        """顯示模組管理頁面"""
        self.main_window._ensure_mod_management_frame()
        if self.main_window.mod_frame:
            self.main_window.mod_frame.load_servers()
        self.show_page_frame(self.main_window.mod_frame)

    def show_page_frame(self, frame) -> None:
        """
        切換至指定的頁面框架

        Args:
            frame: 要顯示的頁面框架元件
        """
        if frame:
            self.main_window.switchTo(frame)

    def _refresh_and_optionally_select(self, auto_select: str) -> None:
        if not hasattr(self.main_window, "manage_server_frame") or not self.main_window.manage_server_frame:
            return

        try:
            self.main_window.manage_server_frame.selected_server = auto_select
            self.main_window.manage_server_frame.refresh_servers()
        except Exception as e:
            logger.bind(component="PageRouter").error(f"自動選取伺服器失敗: {e}")
