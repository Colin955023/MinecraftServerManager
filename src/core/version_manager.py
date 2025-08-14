#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 版本管理器模組
負責從官方 API 取得版本資訊，提供版本查詢、下載和快取管理功能
Minecraft Version Manager Module
Responsible for retrieving version information from official API with version querying, downloading and caching capabilities
"""
# ====== 標準函式庫 ======
from pathlib import Path
import json
import concurrent.futures
import os
# ====== 專案內部模組 ======
from src.utils.http_utils import HTTPUtils
from src.utils.runtime_paths import ensure_dir, get_cache_dir
from src.utils.log_utils import LogUtils

class MinecraftVersionManager:
    """
    Minecraft 版本管理器類別，提供版本查詢和快取管理
    Minecraft version manager class with version querying and cache management capabilities
    """

    # ====== 初始化與快取管理 ======
    # 初始化版本管理器
    def __init__(self):
        """
        初始化 Minecraft 版本管理器
        Initialize Minecraft version manager
        
        Args:
            None
            
        Returns:
            None
        """
        self.version_manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        self.cache_file = str(ensure_dir(get_cache_dir()) / 'mc_versions_cache.json')

    # 儲存本地快取
    def _save_local_cache(self, versions: list):
        """
        儲存版本列表到本地快取檔案
        Save version list to local cache file
        
        Args:
            versions (list): 版本資料列表
            
        Returns:
            None
        """
        try:
            # Ensure cache directory exists before writing
            cache_path = Path(self.cache_file)
            ensure_dir(cache_path.parent)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(versions, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ====== 版本資料獲取 ======
    # 從官方 API 獲取版本列表
    def fetch_versions(self, max_workers: int = 8) -> list:
        """
        從官方 API 取得所有 Minecraft 版本列表並多執行緒查詢詳細資訊
        Fetch all Minecraft version list from official API with multi-threaded detail querying
        
        Args:
            max_workers (int): 最大執行緒數量
            
        Returns:
            list: 版本資料列表
        """
        try:
            data = HTTPUtils.get_json(self.version_manifest_url, timeout=10)
            if not data:
                return []

            versions = []
            for version_data in data.get("versions", []):
                # 只處理正式發布版本，過濾掉快照版本和其他類型
                if version_data["type"] != "release":
                    continue
                    
                vid = version_data["id"]
                new_v = {
                    "id": vid,
                    "type": version_data["type"],
                    "url": version_data["url"],
                    "time": version_data["time"],
                    "releaseTime": version_data["releaseTime"],
                    "complianceLevel": version_data.get("complianceLevel", 0),
                    "server_url": None,
                }
                versions.append(new_v)

            # 多執行緒查詢 server_url
            def fetch_detail(ver):
                try:
                    data = HTTPUtils.get_json(ver["url"], timeout=10)
                    if data:
                        server_info = data.get("downloads", {}).get("server", {})
                        ver["server_url"] = server_info.get("url")
                except Exception:
                    ver["server_url"] = None

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(fetch_detail, versions))
            self._save_local_cache(versions)
            return versions
        except Exception as e:
            LogUtils.error(f"無法取得版本資訊: {e}", "VersionManager")
            return []

    def get_versions(self) -> list:
        """
        取得所有 Minecraft 版本列表，回傳正式發布版本。
        如果快取檔案不存在，會自動獲取版本。
        回傳 dict list，快取中已只包含 release 版本
        """
        try:
            if not os.path.exists(self.cache_file):
                # 快取檔案不存在，自動獲取版本
                self.fetch_versions()
                # 重新檢查快取檔案
                if not os.path.exists(self.cache_file):
                    return []

            with open(self.cache_file, 'r', encoding='utf-8') as f:
                versions = json.load(f)

            # 直接回傳版本列表，快取中已只包含正式發布版本
            return versions
        except Exception as e:
            LogUtils.debug(f"獲取版本時發生錯誤: {e}", "VersionManager")
            return []
