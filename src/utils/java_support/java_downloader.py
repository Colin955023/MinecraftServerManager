"""Java 下載工具模組
提供 Java 安裝包下載與管理功能，支援 Microsoft OpenJDK 的自動下載與安裝流程。
"""

import os
import shutil
from pathlib import Path

from .. import SubprocessUtils, get_logger

logger = get_logger().bind(component="JavaDownloader")


class JavaDownloader:
    """Java 下載管理類別。"""

    @staticmethod
    def _get_winget_path() -> Path | None:
        """
        尋找 winget 的執行路徑。
        優先檢查環境變數 PATH，若找不到則手動推算 Windows App Alias 路徑。
        """
        # 1. 嘗試從系統 PATH 中尋找
        winget_str = shutil.which("winget")
        if winget_str:
            return Path(winget_str)

        # 2. 針對 Nuitka 環境或 PATH 遺失情況，手動檢查預設別名路徑
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            # 使用 pathlib 的 / 運算子串接路徑
            alias_path = Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe"
            if alias_path.exists():
                return alias_path

        return None

    @staticmethod
    def _is_winget_available() -> bool:
        """
        確認 winget 是否可用，並詳細記錄失敗原因以利 Debug。
        """
        winget_path = JavaDownloader._get_winget_path()

        if not winget_path:
            logger.error("在系統 PATH 或預設 App 執行別名路徑中皆找不到 winget.exe")
            return False

        try:
            # 執行版本檢查，確保執行檔不只是「存在」而是「可執行」
            process = SubprocessUtils.run_checked(
                [str(winget_path), "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",  # 確保 Windows 環境下的編碼讀取正確
                stdin=SubprocessUtils.DEVNULL,
                creationflags=SubprocessUtils.CREATE_NO_WINDOW,
            )
            logger.info(f"偵測到 winget，路徑: {winget_path}, 版本: {process.stdout.strip()}")
            return True

        except FileNotFoundError:
            logger.error(f"執行失敗：找不到檔案 {winget_path}，可能權限不足或別名失效。")
            return False
        except SubprocessUtils.CalledProcessError as e:
            # 擷取關鍵的系統錯誤訊息，避免過度冗長的輸出
            error_msg = e.stderr.strip() if e.stderr else "無錯誤輸出 (stderr)"
            logger.error(f"winget 存在但回傳錯誤代碼 ({e.returncode})。錯誤內容: {error_msg}")
            return False
        except Exception as e:
            logger.exception(f"檢查 winget 時發生未預期的異常: {e}")
            return False

    @staticmethod
    def install_java_with_winget(major: int):
        """透過 winget 安裝指定主版本的 Java。

        Args:
            major: Java 主要版本號。
        """

        if not JavaDownloader._is_winget_available():
            raise Exception(
                "無法調用 winget 工具。這可能是因為：\n"
                "1. 系統未安裝「應用程式安裝員 (App Installer)」。\n"
                "2. 您的 Windows 版本過舊。\n"
                "3. 環境變數中缺少 %LocalAppData%\\Microsoft\\WindowsApps。\n"
                "請檢查程式日誌以獲取詳細錯誤代碼。"
            )

        if major == 8:
            pkg = "Oracle.JavaRuntimeEnvironment"
        elif major in (11, 16, 17, 21, 25):
            pkg = f"Microsoft.OpenJDK.{major}"
        else:
            raise Exception(f"不支援自動安裝 Java 主要版本 {major}，請手動前往官網下載。")

        # 執行安裝指令
        winget_cmd = ["winget", "install", "--accept-package-agreements", "--accept-source-agreements", pkg]

        try:
            logger.info(f"正在執行安裝指令: {' '.join(winget_cmd)}")
            SubprocessUtils.run_checked(
                winget_cmd,
                check=True,
                stdin=SubprocessUtils.DEVNULL,
                stdout=SubprocessUtils.PIPE,
                stderr=SubprocessUtils.PIPE,
                creationflags=SubprocessUtils.CREATE_NO_WINDOW,
            )
            logger.info(f"Java {major} ({pkg}) 安裝程序已觸發。")
        except Exception as e:
            logger.exception(f"winget 安裝過程發生異常: {e}")
            raise Exception(f"透過 winget 安裝 {pkg} 失敗。建議手動開啟終端機執行：\nwinget install {pkg}") from e
