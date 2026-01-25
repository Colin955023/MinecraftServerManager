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
from typing import Optional
import json
import concurrent.futures
import os
# ====== 專案內部模組 ======
from src.utils import HTTPUtils, UIUtils, ensure_dir, get_cache_dir
from src.utils.logger import get_logger

logger = get_logger().bind(component="VersionManager")

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
        """
        self.version_manifest_url = (
            "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        )
        self.cache_file = str(ensure_dir(get_cache_dir()) / "mc_versions_cache.json")

    # 儲存本地快取
    def _save_local_cache(self, versions: list) -> None:
        """
        儲存版本列表到本地快取檔案
        Save version list to local cache file

        Args:
            versions (list): 版本資料列表

        Returns:
            None
        """
        try:
            # 在寫入前確保快取目錄存在
            cache_path = Path(self.cache_file)
            ensure_dir(cache_path.parent)
            
            # 檢查資料是否異動，避免不必要的寫入
            if cache_path.exists():
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                    # 若內容一致，直接返回不寫入
                    if existing_data == versions:
                        return
                except Exception:
                    # 讀取或比對失敗則繼續寫入
                    pass
            
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(versions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception(f"寫入版本快取失敗: {e}")

    # ====== 版本資料獲取 ======
    # 從官方 API 獲取版本列表
    def fetch_versions(self, max_workers: int = 10) -> list:
        """
        從官方 API 取得所有 Minecraft 版本列表並多執行緒查詢詳細資訊
        Fetch all Minecraft version list from official API with multi-threaded detail querying

        Args:
            max_workers (int): 最大執行緒數量

        Returns:
            list: 版本資料列表 (僅包含已確認有 server_url 的版本)
        """
        try:
            logger.info("開始從官方 API 獲取版本資訊...")
            data = HTTPUtils.get_json(self.version_manifest_url, timeout=10)
            if not data:
                return []

            # 讀取現有快取以保留已查詢過的 server_url
            cache_map = {}
            if os.path.exists(self.cache_file):
                try:
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        cached_list = json.load(f)
                        for v in cached_list:
                            cache_map[v["id"]] = v
                except Exception:
                    pass

            versions_to_process = []
            final_list = []

            for version_data in data.get("versions", []):
                # 只處理正式發布版本
                if version_data["type"] != "release":
                    continue

                vid = version_data["id"]
                
                # 檢查快取
                cached_v = cache_map.get(vid)
                if cached_v and cached_v.get("server_url") is not None:
                    final_list.append(cached_v)
                else:
                    # 需要查詢的項目
                    new_v = {
                        "id": vid,
                        "type": version_data["type"],
                        "url": version_data["url"],
                        "time": version_data["time"],
                        "releaseTime": version_data["releaseTime"],
                        "complianceLevel": version_data.get("complianceLevel", 0),
                        "server_url": None, # 待查詢
                    }
                    versions_to_process.append(new_v)
                    final_list.append(new_v)

            # 使用多執行緒查詢 server_url (僅針對未快取或狀態未知的版本)
            if versions_to_process:
                logger.info(f"發現 {len(versions_to_process)} 個版本需要更新詳細資訊，開始並行查詢...")
                
                def fetch_server_url(v_obj):
                    try:
                        v_data = HTTPUtils.get_json(v_obj["url"], timeout=10)
                        if v_data:
                            url = v_data.get("downloads", {}).get("server", {}).get("url")
                            v_obj["server_url"] = url if url else "" # 若無 url 則設為空字串，避免下次重複查詢
                        else:
                            # 查詢失敗（網絡問題？），保持 None 以便下次重試
                            pass 
                    except Exception as e:
                        logger.debug(f"查詢版本 {v_obj['id']} 失敗: {e}")

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    list(executor.map(fetch_server_url, versions_to_process))
            self._save_local_cache(final_list)

            # 回傳給 UI 的列表只包含有效的伺服器版本
            valid_versions = [v for v in final_list if v.get("server_url")]
            logger.info(f"版本列表更新完成，共 {len(valid_versions)} 個可用伺服器版本")
            return valid_versions

        except Exception as e:
            logger.exception(f"無法取得版本資訊: {e}")
            UIUtils.show_error("取得版本失敗", f"無法從官方 API 獲取版本資訊: {e}")
            # 發生錯誤時嘗試回傳快取
            return self.get_versions(force_fetch=False)

    def get_server_download_url(self, version_id: str) -> Optional[str]:
        """
        獲取指定版本的伺服器下載 URL
        Get server download URL for specific version
        """
        try:
            versions = self.get_versions(force_fetch=False)
            target_ver = next((v for v in versions if v["id"] == version_id), None)
            
            if target_ver and target_ver.get("server_url"):
                return target_ver["server_url"]
            return None
        except Exception as e:
            logger.exception(f"獲取伺服器下載連結失敗 {version_id}: {e}")
            return None

    def get_versions(self, force_fetch=False) -> list:
        """
        取得 Minecraft 版本列表
        Get Minecraft version list

        Args:
            force_fetch (bool): 是否強制從網路更新

        Returns:
            list: Minecraft 版本列表
        """
        try:
            if force_fetch or not os.path.exists(self.cache_file):
                return self.fetch_versions()

            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    versions = json.load(f)
            except json.JSONDecodeError:
                logger.warning("版本快取檔案損壞，嘗試重新獲取...")
                return self.fetch_versions()

            # 過濾出有有效 server_url 的版本回傳
            valid_versions = [v for v in versions if v.get("server_url")]
            
            if not valid_versions and not force_fetch:
                # 如果快取讀出來是空的（或全無 url），可能需要強制更新一次
                return self.fetch_versions()
                
            return valid_versions
        except Exception as e:
            logger.exception(f"獲取版本時發生錯誤: {e}")
            UIUtils.show_error("獲取版本失敗", f"無法從快取獲取版本資訊: {e}")
            return []
