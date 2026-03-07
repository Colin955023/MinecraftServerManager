#!/usr/bin/env python3
"""
UI 自動化測試框架 - Windows 平台特定
UI Automation Testing Framework - Windows-specific implementation
"""

import importlib.util
import shutil
from enum import Enum
from pathlib import Path

from . import SubprocessUtils, get_logger

logger = get_logger().bind(component="UITestFramework")


def _check_module_via_uv_isolated(package_name: str, module_name: str | None = None) -> bool:
    """使用 uv isolated 檢查套件是否可用，不依賴當前環境是否已安裝。"""
    uv_bin = shutil.which("uv")
    if uv_bin is None:
        logger.error("找不到 uv，無法使用 --isolated 檢查套件")
        return False

    import_name = module_name or package_name
    cmd = [
        uv_bin,
        "run",
        "--isolated",
        "--with",
        package_name,
        "python",
        "-c",
        f"import {import_name}",
    ]
    try:
        completed = SubprocessUtils.run_checked(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except Exception as e:
        logger.error(f"uv isolated 檢查失敗 ({package_name}): {e}")
        return False

    if completed.returncode == 0:
        return True

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    detail = stderr or stdout or "unknown error"
    logger.error(f"uv isolated 檢查未通過 ({package_name}): {detail}")
    return False


class UITestFramework(Enum):
    """支援的 UI 測試框架"""

    PYWINAUTO = "pywinauto"
    PLAYWRIGHT = "playwright"
    NONE = "none"


class UITestConfig:
    """UI 測試組態"""

    def __init__(self, framework: UITestFramework = UITestFramework.PYWINAUTO, timeout: float = 30.0):
        """
        初始化 UI 測試組態
        Args:
            framework: 選用的測試框架 (pywinauto 用於 Windows UI，Playwright 用於網頁)
            timeout: 操作超時時間（秒）
        """
        self.framework = framework
        self.timeout = timeout
        self.exe_path: Path | None = None

    def set_application_path(self, path: str) -> None:
        """設定應用程式執行檔路徑"""
        self.exe_path = Path(path)
        if not self.exe_path.exists():
            raise FileNotFoundError(f"應用程式不存在: {path}")


class WindowsUITestEngine:
    """Windows 平台 UI 測試引擎"""

    def __init__(self, config: UITestConfig):
        """初始化測試引擎"""
        self.config = config
        self.app = None
        self.window = None

    def setup(self) -> bool:
        """設定測試環境"""
        try:
            if self.config.framework == UITestFramework.PYWINAUTO:
                return self._setup_pywinauto()
            if self.config.framework == UITestFramework.PLAYWRIGHT:
                logger.warning("Playwright 主要用於網頁測試，如需 Windows UI 測試建議使用 pywinauto")
                return self._setup_playwright()
            logger.error(f"不支援的測試框架: {self.config.framework}")
            return False
        except ImportError as e:
            logger.error(f"缺少測試框架依賴: {e}")
            logger.info("請執行: pip install pywinauto 或 pip install playwright")
            return False

    def _setup_pywinauto(self) -> bool:
        """設定 pywinauto 框架"""
        if not _check_module_via_uv_isolated("pywinauto"):
            logger.error("pywinauto 無法在 uv --isolated 環境使用")
            return False
        logger.info("pywinauto UI 測試框架已就緒（uv --isolated）")
        return True

    def _setup_playwright(self) -> bool:
        """設定 Playwright 框架"""
        if not _check_module_via_uv_isolated("playwright"):
            logger.error("Playwright 無法在 uv --isolated 環境使用")
            return False
        logger.info("Playwright UI 測試框架已就緒（uv --isolated）")
        return True

    def launch_application(self) -> bool:
        """啟動應用程式"""
        if not self.config.exe_path:
            logger.error("應用程式路徑未設定")
            return False

        try:
            if self.config.framework == UITestFramework.PYWINAUTO:
                if importlib.util.find_spec("pywinauto") is None:
                    logger.error("目前執行環境缺少 pywinauto，請用 uv --isolated 執行此測試流程")
                    return False
                return self._launch_pywinauto()
            return False
        except Exception as e:
            logger.error(f"應用程式啟動失敗: {e}")
            return False

    def _launch_pywinauto(self) -> bool:
        """使用 pywinauto 啟動應用程式"""
        try:
            import pywinauto  # type: ignore[import-not-found,import-error]

            self.app = pywinauto.Application().start(str(self.config.exe_path))  # type: ignore[attr-defined]
            self.window = self.app.window()  # type: ignore[attr-defined]
            logger.info(f"應用程式已啟動: {self.config.exe_path}")
            return True
        except Exception as e:
            logger.error(f"pywinauto 啟動失敗: {e}")
            return False

    def teardown(self) -> None:
        """清理測試環境"""
        try:
            if self.app:
                self.app.kill()  # type: ignore[attr-defined]
                logger.info("應用程式已關閉")
        except Exception as e:
            logger.warning(f"應用程式關閉出錯: {e}")

    def get_statistics(self) -> dict:
        """取得測試統計資訊"""
        return {
            "framework": self.config.framework.value,
            "timeout": self.config.timeout,
            "exe_path": str(self.config.exe_path) if self.config.exe_path else None,
            "is_setup": self.app is not None,
        }


# 推薦的測試框架選擇
def recommend_ui_test_framework() -> UITestFramework:
    """根據平台和可用性推薦測試框架"""
    import platform

    system = platform.system()

    if system == "Windows":
        # Windows 平台優先使用 pywinauto（原生 UI 測試）
        if _check_module_via_uv_isolated("pywinauto"):
            return UITestFramework.PYWINAUTO
        if _check_module_via_uv_isolated("playwright"):
            logger.warning("找不到可用的 pywinauto isolated 環境，回退 Playwright")
            return UITestFramework.PLAYWRIGHT

        logger.warning("找不到可用的 UI 測試框架（uv --isolated）")
        return UITestFramework.NONE

    logger.warning(f"當前平台 {system} 未提供完整 UI 測試支援")
    return UITestFramework.NONE
