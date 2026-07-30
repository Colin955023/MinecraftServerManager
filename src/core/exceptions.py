"""
應用層共用異常型別。

所有應用層例外皆繼承自 `AppException`，呼叫端可以用它一次攔截所有應用層
錯誤；也可以改用底下更細分的子類別，只攔截特定失敗類型，不必攔截並解析
泛用的 `Exception`。

註：這裡目前只新增例外類別本身，尚未回頭把既有各模組的 `raise` 語句
遷移到對應的細分類別——那是後續各模組逐步導入的工作。新增類別不影響
現有的 `except AppException` / `except ConfigurationError` 呼叫點。
"""

from __future__ import annotations


class AppException(Exception):
    """應用程式層的基底異常。"""


class ConfigurationError(AppException):
    """設定無效、缺失或無法使用。"""


class NetworkError(AppException):
    """對外部服務（如 Modrinth API）的網路請求失敗。"""


class DownloadVerificationError(AppException):
    """下載檔案的雜湊或大小驗證失敗，內容不可信任。"""


class ModInstallError(AppException):
    """模組安裝、匯入或移除流程失敗。"""


class DependencyResolutionError(AppException):
    """模組依賴解析或版本相容性檢查失敗。"""


class ServerProcessError(AppException):
    """啟動、停止或監控 Minecraft 伺服器行程時失敗。"""


class ArchiveSecurityError(AppException):
    """壓縮檔內容未通過安全檢查（例如路徑穿越、symlink、大小超限）。"""
