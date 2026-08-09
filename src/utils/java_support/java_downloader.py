"""
Java 下載工具模組
提供 Java 安裝包下載與管理功能，支援 Microsoft OpenJDK 的自動下載與安裝流程
"""

from ...core import JavaInstallError
from .. import SubprocessUtils, get_logger

logger = get_logger().bind(component="JavaDownloader")


class JavaDownloader:
    """Java 下載管理類別"""

    @staticmethod
    def _is_winget_available() -> bool:
        """
        確認 winget 是否可用，並詳細記錄失敗原因以利 Debug
        """
        try:
            process = SubprocessUtils.query_winget(["--version"], check=True)
            logger.info(f"偵測到 winget，版本: {process.stdout.strip()}")
            return True

        except FileNotFoundError:
            logger.error("執行失敗：找不到 winget，可能權限不足或別名失效")
            return False
        except SubprocessUtils.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "無錯誤輸出 (stderr)"
            logger.error(f"winget 存在但回傳錯誤代碼 ({e.returncode})錯誤內容: {error_msg}")
            return False
        except Exception as e:
            logger.exception(f"檢查 winget 時發生未預期的異常: {e}")
            return False

    @staticmethod
    def install_java_with_winget(major: int):
        """
        透過 winget 安裝指定主版本的 Java

        Args:
            major: Java 主要版本號
        """

        if not JavaDownloader._is_winget_available():
            raise JavaInstallError(
                "無法調用 winget 工具這可能是因為：\n"
                "1. 系統未安裝「應用程式安裝員 (App Installer)」\n"
                "2. 您的 Windows 版本過舊\n"
                "3. 環境變數中缺少 %LocalAppData%\\Microsoft\\WindowsApps\n"
                "請檢查程式日誌以獲取詳細錯誤代碼"
            )

        if major == 8:
            pkg = "Oracle.JavaRuntimeEnvironment"
        elif major in (11, 16, 17, 21, 25):
            pkg = f"Microsoft.OpenJDK.{major}"
        else:
            raise JavaInstallError(f"不支援自動安裝 Java 主要版本 {major}，請手動前往官網下載")

        try:
            logger.info(f"正在執行安裝指令: winget install {pkg}")
            SubprocessUtils.query_winget(
                ["install", "--accept-package-agreements", "--accept-source-agreements", pkg], check=True
            )
            logger.info(f"Java {major} ({pkg}) 安裝程序已完成")
        except Exception as e:
            logger.exception(f"winget 安裝過程發生異常: {e}")
            raise JavaInstallError(f"透過 winget 安裝 {pkg} 失敗建議手動開啟終端機執行：\nwinget install {pkg}") from e
