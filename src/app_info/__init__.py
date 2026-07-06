"""版本資訊套件
提供應用程式版本與發佈資訊的延遲匯出入口。
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "APP_VERSION": (".app_info", "APP_VERSION"),
    "APP_NAME": (".app_info", "APP_NAME"),
    "APP_DESCRIPTION": (".app_info", "APP_DESCRIPTION"),
    "GITHUB_OWNER": (".app_info", "GITHUB_OWNER"),
    "GITHUB_REPO": (".app_info", "GITHUB_REPO"),
    "APP_ID": (".app_info", "APP_ID"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
