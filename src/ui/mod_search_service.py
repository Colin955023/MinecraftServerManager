#!/usr/bin/env python3
"""Mod 查詢服務
提供線上模組搜尋與本地模組資訊增強。
"""

from __future__ import annotations

import re

from src.version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

from ..utils import HTTPUtils, PathUtils, get_logger

logger = get_logger().bind(component="ModSearchService")


def search_mods_online(
    query: str,
    minecraft_version: str | None = None,
    _loader: str | None = None,
    categories: list[str] | None = None,
    sort_by: str = "relevance",
) -> list[object]:
    """
    線上搜尋模組。
    注意：_loader 參數目前僅為介面相容性保留，Modrinth 搜尋 API 尚不支援依 loader 過濾，因此此參數未被使用。
    """
    url = "https://api.modrinth.com/v2/search"
    facets = [["project_type:mod"]]
    if minecraft_version:
        facets.append([f"game_versions:{minecraft_version}"])
    # loader 不直接加到 facets，API 不支援
    if categories:
        category_facets = [f"categories:{cat}" for cat in categories]
        facets.append(category_facets)
    params = {
        "query": query,
        "limit": 20,
        "facets": PathUtils.to_json_str(facets),
        "index": (sort_by if sort_by in ["relevance", "downloads", "newest"] else "relevance"),
    }
    headers = {"User-Agent": f"MinecraftServerManager/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"}
    response = HTTPUtils.get_json(url=url, headers=headers, params=params, timeout=10)
    if not response:
        logger.error("Modrinth API request failed")
        return []
    hits = response.get("hits", [])
    mods = []
    for hit in hits:
        mod = type("OnlineModInfo", (), {})()
        mod.name = hit.get("title", "Unknown")
        mod.slug = hit.get("project_id", "")
        mod.url = f"https://modrinth.com/mod/{hit.get('slug', hit.get('project_id', ''))}"
        mod.versions = hit.get("versions", [])
        mod.available = True
        mod.download_url = None
        mod.filename = None
        mod.author = hit.get("author", "?")
        mod.description = hit.get("description", "")
        mod.homepage_url = hit.get("homepage_url", mod.url)
        mod.latest_version = hit.get("latest_version", "")
        mod.download_count = hit.get("downloads", 0)
        mod.source = "modrinth"
        mods.append(mod)
    if sort_by == "downloads":
        mods.sort(key=lambda x: getattr(x, "download_count", 0), reverse=True)
    elif sort_by == "name":
        mods.sort(key=lambda x: x.name.lower())
    return mods


def enhance_local_mod(filename: str) -> object | None:
    """增強本地模組資訊，從線上查詢模組詳細資訊。"""
    name = filename.replace(".jar", "").replace(".jar.disabled", "")
    for suffix in ["-fabric", "-forge", "-mc"]:
        if suffix in name.lower():
            name = name.lower().split(suffix)[0]
            break
    name = re.sub(r"-[\d\.\+]+.*$", "", name)
    # 將底線與連字號都轉成空白，避免搜尋 API 查不到
    name = name.replace("_", "").replace("-", " ").strip()
    mods = search_mods_online(name)
    if mods:
        return mods[0]
    return None
