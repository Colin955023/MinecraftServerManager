"""
背景任務協調器
負責處理主視窗啟動時的初始化任務與背景資料預載
"""

from __future__ import annotations

import traceback
from contextlib import suppress
from typing import TYPE_CHECKING

from src.utils import (
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    JavaUtils,
    UIUtils,
    UpdateChecker,
    get_logger,
    get_settings_manager,
    is_qobject_alive,
)

if TYPE_CHECKING:
    from src.ui import MainWindow

logger = get_logger().bind(component="TaskCoordinator")


class TaskCoordinator:
    """背景任務協調器"""

    def __init__(self, main_window: MainWindow):
        self.main_window = main_window

    def preload_java_candidates(self) -> None:
        """啟動時背景掃描本機 Java 並更新快取"""

        def refresh_java_cache():
            JavaUtils.refresh_java_candidates_cache()

        if hasattr(self.main_window, "scope") and self.main_window.scope:
            self.main_window.scope.submit(refresh_java_cache, key="preload_java", replace=True)

    def handle_startup_tasks(self) -> None:
        """處理啟動時的任務：首次執行提示和自動更新檢查"""
        settings = get_settings_manager()
        if not settings.is_first_run_completed():
            self._show_first_run_prompt()
        elif settings.is_auto_update_enabled():
            self._schedule_startup_update_check(delay_ms=600, show_msg=False)

    def check_for_updates(self, show_msg: bool = True) -> None:
        """
        檢查程式更新

        Args:
            show_msg: 若為 True，則在版本已是最新時顯示提示訊息
        """
        try:
            UpdateChecker.check_and_prompt_update(
                APP_VERSION,
                GITHUB_OWNER,
                GITHUB_REPO,
                show_up_to_date_message=show_msg,
                parent=self.main_window.root,
                work_scope=getattr(self.main_window, "scope", None),
            )
        except Exception as e:
            logger.error(f"自動更新檢查失敗: {e}\n{traceback.format_exc()}")
            if show_msg:
                UIUtils.show_message("更新檢查失敗", f"無法檢查更新：{e}", self.main_window.root, message_level="error")

    def manual_check_updates(self) -> None:
        """手動觸發更新檢查，並始終顯示結果訊息"""
        self.check_for_updates(show_msg=True)

    def _schedule_startup_update_check(self, *, delay_ms: int = 600, show_msg: bool = False) -> None:
        """延遲啟動更新檢查，避開 modal 對話框剛關閉時的 UI 卡頓"""

        def _run_update_check() -> None:
            if not getattr(self.main_window, "root", None):
                return
            if not is_qobject_alive(self.main_window.root):
                return
            self.check_for_updates(show_msg=show_msg)

        UIUtils.schedule_debounce(
            self.main_window.root, "_startup_update_check_job", max(0, int(delay_ms)), _run_update_check, owner=self
        )

    def _show_first_run_prompt(self) -> None:
        """首次執行時直接啟用自動更新並提示使用者"""
        settings = get_settings_manager()
        settings.set_auto_update_enabled(True)
        settings.mark_first_run_completed()

        UIUtils.show_message(
            title="歡迎使用 Minecraft 伺服器管理器",
            message="預設已啟用自動檢查更新功能，程式將在啟動時自動檢查新版本\n您可於「關於」視窗中隨時關閉此功能。",
            parent=self.main_window.root,
            message_level="info",
        )

        with suppress(Exception):
            self.main_window.root.setFocus()

        self._schedule_startup_update_check(delay_ms=900, show_msg=False)


__all__ = ["TaskCoordinator"]
