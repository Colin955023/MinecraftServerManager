"""版本資訊與應用程式常數 (package)

此資料夾用於分類版本資訊；對外維持舊版匯入相容：
from src.version_info import APP_NAME, APP_VERSION, ...
"""

from .version_info import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    VERSION_PREFIX,
)

__all__ = [
    "APP_DESCRIPTION",
    "APP_NAME",
    "APP_VERSION",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "VERSION_PREFIX",
]
