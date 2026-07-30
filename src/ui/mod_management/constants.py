"""模組管理頁面共用常數。"""

from __future__ import annotations

from ...utils import get_logger

logger = get_logger().bind(component="ModManagement")
SUPPORTED_ONLINE_MOD_LOADERS = {"fabric", "forge", "quilt", "neoforge"}
MODRINTH_PROJECT_PAGE_BASE_URL = "https://modrinth.com/mod"

MOD_MANAGEMENT_UI_SCALE = 0.8

__all__ = [
    "MODRINTH_PROJECT_PAGE_BASE_URL",
    "MOD_MANAGEMENT_UI_SCALE",
    "SUPPORTED_ONLINE_MOD_LOADERS",
    "logger",
]
