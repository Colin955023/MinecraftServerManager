"""Mod 查詢服務共用常數"""

from __future__ import annotations

from src.utils import get_logger

logger = get_logger().bind(component="ModSearchService")
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_URL = "https://modrinth.com/mod"
MODRINTH_PROJECT_BATCH_URL = "https://api.modrinth.com/v2/projects"
MODRINTH_VERSION_URL_TEMPLATE = "https://api.modrinth.com/v2/project/{project_id}/version"
MODRINTH_VERSION_DETAIL_URL_TEMPLATE = "https://api.modrinth.com/v2/version/{version_id}"
MODRINTH_VERSION_FILES_URL = "https://api.modrinth.com/v2/version_files"
MODRINTH_VERSION_FILES_UPDATE_URL = "https://api.modrinth.com/v2/version_files/update"
MODRINTH_SEARCH_TIMEOUT_SECONDS = 15
MODRINTH_VERSION_TIMEOUT_SECONDS = 15
MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS = 12
MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS = 12
MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS = 12
MODRINTH_VERSION_FILES_TIMEOUT_SECONDS = 20
SUPPORTED_SORT_OPTIONS = {"relevance", "downloads", "newest", "updated", "follows"}
MODRINTH_BATCH_HASH_LOOKUP_SIZE = 64
MODRINTH_BATCH_PROJECT_LOOKUP_SIZE = 64
