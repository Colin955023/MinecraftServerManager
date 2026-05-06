"""模組管理頁面共用常數。"""

from __future__ import annotations

from ...utils import Colors, get_logger

logger = get_logger().bind(component="ModManagement")
SUPPORTED_ONLINE_MOD_LOADERS = {"fabric", "forge", "quilt", "neoforge"}
MODRINTH_PROJECT_PAGE_BASE_URL = "https://modrinth.com/mod"
MOD_TOOL_BUTTON_STYLE = {
    "fg_color": Colors.BUTTON_LIGHT,
    "hover_color": Colors.BUTTON_LIGHT_HOVER,
    "text_color": Colors.TEXT_ON_LIGHT,
    "border_color": Colors.BORDER_LIGHT,
}

__all__ = [
    "MODRINTH_PROJECT_PAGE_BASE_URL",
    "MOD_TOOL_BUTTON_STYLE",
    "SUPPORTED_ONLINE_MOD_LOADERS",
    "logger",
]
