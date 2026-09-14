"""
Java 下載工具模組
提供 Java 安裝套件下載與管理功能，支援 Microsoft OpenJDK 的自動下載與安裝流程
"""

from __future__ import annotations

from src.utils import JavaInstallError, SubprocessUtils, get_logger

logger = get_logger().bind(component="JavaDownloader")


class JavaDownloader:
    """Java 下載管理類別"""

    @staticmethod
    def _is_winget_available() -> bool:
        """
        確認 winget 是否可用，並詳細記錄失敗原因以利 Debug
        """
        try:
            process = SubprocessUtils.run_checked(
                ["winget", "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
                stdin=SubprocessUtils.DEVNULL,
                creationflags=SubprocessUtils.CREATE_NO_WINDOW,
            )
            logger.info(f"偵測到 winget，版本: {process.stdout.strip()}")
            return True

        except FileNotFoundError:
            logger.error("執行失敗：找不到 winget，可能權限不足或別名失效")
            return False
        except SubprocessUtils.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "無錯誤輸出 (stderr)"
            logger.error(f"winget 存在但回傳錯誤代碼 ({e.returncode})，錯誤內容: {error_msg}")
            return False
        except Exception as e:
            logger.exception(f"檢查 winget 時發生未預期的錯誤: {e}")
            return False

    @staticmethod
    def install_java_with_winget(major: int):
        """
        透過 winget 安裝指定主版本的 Java

        Args:
            major: Java 主要版本號
        """

        if not JavaDownloader._is_winget_available():
            raise JavaInstallError("無法呼叫 winget 工具，請確認系統已安裝「應用程式安裝員 (App Installer)」")

        if major == 8:
            pkg = "Oracle.JavaRuntimeEnvironment"
        elif major in (11, 16, 17, 21, 25):
            pkg = f"Microsoft.OpenJDK.{major}"
        else:
            raise JavaInstallError(f"不支援自動安裝 Java 主要版本 {major}，請手動前往官網下載")

        try:
            logger.info(f"正在執行安裝指令: winget install {pkg}")
            returncode = SubprocessUtils.run_winget_interactive(
                ["install", "--accept-package-agreements", "--accept-source-agreements", pkg]
            )
            if returncode != 0:
                code_unsigned = returncode & 0xFFFFFFFF
                code_hex = hex(code_unsigned)
                error_map = {
                    1602: "使用者取消安裝",
                    1603: "安裝過程發生嚴重錯誤",
                    1618: "另一個安裝程式正在執行中，請稍後重試",
                    0x800704C7: "使用者取消安裝或拒絕 UAC 驗證",
                    0x80070005: "存取被拒，需要管理員權限",
                    0x8A150008: "下載套件失敗",
                    0x8A15000F: "下載套件逾時或網路連線中斷",
                    0x8A150011: f"未在來源找到指定的 Java 套件 ({pkg})",
                    0x8A150014: "套件雜湊值不相符，檔案可能損毀",
                    0x8A15002B: "授權條款未接受",
                    0x8A15002C: "系統環境或架構不支援此套件",
                    0x8A150044: "安裝程式執行失敗",
                    0x8A150056: f"系統已安裝此版本 ({pkg})",
                }
                reason = error_map.get(code_unsigned)
                if reason:
                    raise JavaInstallError(f"透過 winget 安裝 {pkg} 失敗：{reason} (代碼: {code_hex})")
                raise JavaInstallError(f"透過 winget 安裝 {pkg} 失敗 (結束代碼: {code_hex})")
            logger.info(f"Java {major} ({pkg}) 安裝程序已完成")
        except JavaInstallError:
            raise
        except Exception as e:
            logger.exception(f"winget 安裝過程發生錯誤: {e}")
            raise JavaInstallError(f"透過 winget 安裝 {pkg} 失敗：{e}") from e


__all__ = ["JavaDownloader"]
