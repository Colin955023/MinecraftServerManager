"""共用異常型別定義"""

from __future__ import annotations


class AppException(Exception):
    """應用程式層的基底異常"""


class ConfigurationError(AppException):
    """設定無效、缺失或無法使用"""


class ArchiveSecurityError(AppException, ValueError):
    """壓縮檔內容未通過安全檢查（例如路徑穿越、symlink、大小超限）"""


class JavaInstallError(AppException):
    """Java 自動安裝流程失敗或指定版本不支援"""


class NetworkSecurityError(ValueError):
    """HTTP 請求因 URL 或重新導向安全策略而被拒絕"""


class ResponseTooLargeError(ValueError):
    """HTTP 回應超過本機允許的記憶體上限"""


class ProviderIdentityPersistenceError(AppException, RuntimeError):
    """Provider 身份持久化儲存失敗"""


class OperationCancelledError(AppException):
    """使用者主動取消非同步或耗時作業"""


class CreationCancelledError(OperationCancelledError):
    """伺服器建立流程被使用者取消"""


class ImportCancelledError(OperationCancelledError):
    """伺服器匯入流程被使用者取消"""


__all__ = [
    "AppException",
    "ArchiveSecurityError",
    "ConfigurationError",
    "CreationCancelledError",
    "ImportCancelledError",
    "JavaInstallError",
    "NetworkSecurityError",
    "OperationCancelledError",
    "ProviderIdentityPersistenceError",
    "ResponseTooLargeError",
]
