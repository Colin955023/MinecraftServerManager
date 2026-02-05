#!/usr/bin/env python3
"""Minecraft 版本管理器模組
負責從官方 API 取得版本資訊，提供版本查詢、下載和快取管理功能
Minecraft Version Manager Module
Responsible for retrieving version information from official API with version querying, downloading and caching capabilities
"""

import concurrent.futures
import threading
from pathlib import Path

from src.utils import (
    HTTPUtils,
    PathUtils,
    RuntimePaths,
    Singleton,
    UIUtils,
    get_logger,
)

logger = get_logger().bind(component="VersionManager")


class MinecraftVersionManager(Singleton):
    """Minecraft 版本管理器類別，提供版本查詢和快取管理"""

    # ====== 初始化與快取管理 ======
    _initialized: bool = False

    def __init__(self):
        if self._initialized:
            return

        self.version_manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest.json"
        self.cache_file = str(RuntimePaths.ensure_dir(RuntimePaths.get_cache_dir()) / "mc_versions_cache.json")
        self._lock = threading.Lock()
        self._initialized = True

    @staticmethod
    def _has_valid_server_url(version: dict) -> bool:
        """檢查版本是否有有效的伺服器下載 URL"""
        url = version.get("server_url")
        return url is not None and url != ""

    # 儲存本地快取
    def _save_local_cache(self, versions: list) -> None:
        """儲存版本列表到本地快取檔案"""
        try:
            # 在寫入前確保快取目錄存在
            cache_path = Path(self.cache_file)
            RuntimePaths.ensure_dir(cache_path.parent)

            # 檢查資料是否異動，避免不必要的寫入
            existing_data = PathUtils.load_json(cache_path)
            if existing_data == versions:
                return

            PathUtils.save_json(cache_path, versions)
        except Exception as e:
            logger.exception(f"寫入版本快取失敗: {e}")

    # ====== 版本資料獲取 ======
    # 從官方 API 獲取版本列表
    def fetch_versions(self, max_workers: int = 10) -> list:
        """從官方 API 取得所有 Minecraft 版本列表並多執行緒查詢詳細資訊"""
        with self._lock:
            try:
                logger.debug("正在獲取官方版本清單...")
                data = HTTPUtils.get_json(self.version_manifest_url, timeout=10)
                if not data:
                    return []

                cache_path = Path(self.cache_file)

                # 讀取現有快取以保留已查詢過的 server_url
                cache_map = {}
                cached_list = PathUtils.load_json(cache_path)
                if cached_list:
                    for v in cached_list:
                        cache_map[v["id"]] = v

                versions_to_process = []
                final_list = []

                for version_data in data.get("versions", []):
                    # 只處理正式發布版本
                    if version_data["type"] != "release":
                        continue

                    vid = version_data["id"]

                    # 檢查快取
                    cached_v = cache_map.get(vid)
                    if (
                        cached_v
                        and cached_v.get("time") == version_data["time"]
                        and cached_v.get("server_url") is not None
                    ):
                        final_list.append(cached_v)
                    else:
                        new_v = {
                            "id": vid,
                            "type": version_data["type"],
                            "url": version_data["url"],
                            "time": version_data["time"],
                            "releaseTime": version_data["releaseTime"],
                            "complianceLevel": version_data.get("complianceLevel", 0),
                            "server_url": None,  # 待查詢
                        }
                        versions_to_process.append(new_v)
                        final_list.append(new_v)

                # 使用多執行緒查詢 server_url (僅針對未快取或狀態未知的版本)
                if versions_to_process:
                    logger.debug(
                        f"版本清單比對完成: 共 {len(versions_to_process)} 個新版本或缺漏資訊，開始同步詳細資訊..."
                    )

                    def fetch_server_url(v_obj):
                        try:
                            v_data = HTTPUtils.get_json(v_obj["url"], timeout=10)
                            if v_data:
                                url = v_data.get("downloads", {}).get("server", {}).get("url")
                                v_obj["server_url"] = url if url else ""  # 若無 url 則設為空字串，避免下次重複查詢
                            else:
                                # 查詢失敗（網絡問題？），保持 None 以便下次重試
                                pass
                        except Exception as e:
                            logger.debug(f"查詢版本 {v_obj['id']} 失敗: {e}")

                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        list(executor.map(fetch_server_url, versions_to_process))
                else:
                    logger.debug("版本清單比對完成: 所有版本資訊皆為最新。")

                self._save_local_cache(final_list)

                # 回傳給 UI 的列表只包含有效的伺服器版本
                valid_versions = [v for v in final_list if self._has_valid_server_url(v)]
                logger.info(f"版本列表更新完成，共 {len(valid_versions)} 個可用伺服器版本")
                return valid_versions

            except Exception as e:
                logger.exception(f"無法取得版本資訊: {e}")
                UIUtils.show_error("取得版本失敗", f"無法從官方 API 獲取版本資訊: {e}")
                return self.get_versions(force_fetch=False)

    def get_server_download_url(self, version_id: str) -> str | None:
        """獲取指定版本的伺服器下載 URL"""
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
        """取得 Minecraft 版本列表，優先從本地快取讀取，必要時從官方 API 獲取"""
        try:
            cache_path = Path(self.cache_file)
            if force_fetch or not cache_path.exists():
                return self.fetch_versions()

            versions = PathUtils.load_json(cache_path)
            if not versions:
                logger.warning("版本快取檔案損壞，嘗試重新獲取...")
                return self.fetch_versions()

            # 過濾出有有效 server_url 的版本回傳
            valid_versions = [v for v in versions if self._has_valid_server_url(v)]

            if not valid_versions and not force_fetch:
                # 如果快取讀出來是空的（或全無 url），可能需要強制更新一次
                return self.fetch_versions()

            return valid_versions
        except Exception as e:
            logger.exception(f"獲取版本時發生錯誤: {e}")
            UIUtils.show_error("獲取版本失敗", f"無法從快取獲取版本資訊: {e}")
            return []
