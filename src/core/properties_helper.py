#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.properties 資訊提供器
提供 server.properties 各項設定的說明
Server properties information provider
Provides descriptions for each setting in server.properties
"""
# ====== 標準函式庫 ======
from pathlib import Path
from typing import Dict
# ====== 專案內部模組 ======
from ..utils.log_utils import LogUtils

class ServerPropertiesHelper:
    """
    server.properties 說明助手：提供屬性說明、分類、載入/儲存等功能。
    ServerPropertiesHelper: A helper class for server.properties, providing property descriptions, categories, loading/saving functions.
    """
    # ====== 屬性說明與描述 ======
    # 取得所有屬性的詳細說明
    @staticmethod
    def get_property_descriptions() -> Dict[str, str]:
        """
        取得所有 server.properties 屬性的中文說明字典
        Get detailed Chinese descriptions for all server.properties attributes

        Args:
            None

        Returns:
            Dict[str, str]: 屬性名稱對應說明的字典
        """
        return {
            "accepts-transfers": "是否允許玩家之間傳送資料（通常為 false，特殊伺服器用）",
            "allow-flight": "是否允許飛行 (true/false)。通常用於創造模式或安裝了飛行模組。",
            "allow-nether": "是否啟用地獄 (true/false)。設為 false 會禁用地獄傳送門。",
            "broadcast-console-to-ops": "是否向管理員廣播控制台訊息 (true/false)。",
            "broadcast-rcon-to-ops": "是否向管理員廣播 RCON 訊息 (true/false)。",
            "bug-report-link": "回報錯誤的網址（通常留空）",
            "difficulty": "遊戲難度 (peaceful, easy, normal, hard)。影響怪物生成和傷害量。",
            "enable-command-block": "是否啟用指令方塊 (true/false)。允許使用指令方塊執行指令。",
            "enable-jmx-monitoring": "是否啟用 JMX 監控 (true/false)。用於效能監控和除錯。",
            "enable-query": "是否啟用查詢 (true/false)。允許外部工具查詢伺服器狀態。",
            "enable-rcon": "是否啟用遠端控制台 (true/false)。允許透過 RCON 協議遠端管理。",
            "enable-status": "是否啟用狀態查詢 (true/false)。允許客戶端查詢伺服器資訊。",
            "enforce-secure-profile": "是否強制啟用安全檔案（true/false，建議保持 true）",
            "enforce-whitelist": "是否強制啟用白名單 (true/false)。只有白名單玩家可加入。",
            "entity-broadcast-range-percentage": "實體廣播範圍百分比 (10-1000，預設: 100)。影響實體的可見距離。",
            "force-gamemode": "是否強制遊戲模式 (true/false)。玩家加入時會被設為預設遊戲模式。",
            "function-permission-level": "函數權限等級 (1-4)。控制資料包函數的權限等級。",
            "gamemode": "新玩家的預設遊戲模式 (survival, creative, adventure, spectator)。",
            "generate-structures": "是否生成結構如村莊、要塞等 (true/false)。",
            "generator-settings": "世界生成器設定（JSON 格式，通常留空）",
            "hardcore": "是否啟用極限模式 (true/false)。玩家死亡後將被禁止進入伺服器。",
            "hide-online-players": "是否隱藏在線玩家 (true/false)。在伺服器列表中隱藏玩家數量。",
            "initial-disabled-packs": "初始停用的資源包（逗號分隔，通常留空）",
            "initial-enabled-packs": "初始啟用的資源包（逗號分隔，預設: vanilla）",
            "level-name": "世界資料夾名稱 (預設: 'world')。伺服器會在此資料夾中儲存世界資料。",
            "level-seed": "世界種子碼。留空則隨機生成。相同種子會產生相同的世界。",
            "level-type": "世界類型 (minecraft:normal, minecraft:flat, minecraft:large_biomes 等)。",
            "log-ips": "是否記錄 IP 位址 (true/false)。在日誌中記錄玩家的 IP 位址。",
            "max-chained-neighbor-updates": "最大連鎖方塊更新數（預設: 1000000）",
            "max-players": "同時在線玩家的最大數量 (預設: 20)。當達到此限制時，新玩家將無法加入。",
            "max-tick-time": "最大 tick 時間 (毫秒，預設: 60000)。超過此時間伺服器會停止。",
            "max-world-size": "世界的最大半徑 (預設: 29999984)。超出此範圍的區域將無法生成。",
            "motd": "伺服器訊息，在多人遊戲列表中顯示 (預設: 'A Minecraft Server')。支援格式化代碼。",
            "network-compression-threshold": "網路壓縮閾值 (預設: 256)。封包大小超過此值時會被壓縮。",
            "online-mode": "是否驗證玩家帳號 (true/false)。建議保持為 true 以確保安全性。",
            "op-permission-level": "管理員權限等級 (1-4)。4 為最高權限，可使用所有指令。",
            "pause-when-empty-seconds": "伺服器無人時自動暫停的秒數（預設: 60）",
            "player-idle-timeout": "玩家閒置超時時間 (分鐘，0=停用)。閒置超過此時間的玩家會被踢出。",
            "prevent-proxy-connections": "是否阻止代理連接 (true/false)。可防止某些類型的作弊。",
            "pvp": "是否允許玩家對戰 (true/false)。設為 false 時玩家無法攻擊其他玩家。",
            "query.port": "查詢埠號 (預設: 25565)。查詢協議使用的埠號。",
            "rate-limit": "速率限制 (0=停用)。限制玩家每秒鐘能傳送的封包數量。",
            "rcon.password": "RCON 密碼。連接遠端控制台時需要的密碼。",
            "rcon.port": "RCON 埠號 (預設: 25575)。遠端控制台使用的埠號。",
            "region-file-compression": "區域檔案壓縮格式（如 deflate，預設）",
            "require-resource-pack": "是否要求資源包 (true/false)。玩家必須接受資源包才能遊玩。",
            "resource-pack": "資源包下載 URL。玩家加入時會自動下載指定的資源包。",
            "resource-pack-id": "資源包唯一識別碼（通常留空）",
            "resource-pack-prompt": "資源包提示訊息。玩家下載資源包時顯示的訊息。",
            "resource-pack-sha1": "資源包的 SHA1 雜湊值，用於驗證檔案完整性。",
            "server-ip": "伺服器綁定的 IP 位址。留空則綁定所有可用的網路介面。",
            "server-port": "伺服器監聽的埠號 (預設: 25565)。請確保此埠號未被其他程式使用。",
            "simulation-distance": "模擬距離 (3-32，預設: 10)。決定區塊的更新範圍。",
            "spawn-monsters": "是否生成敵對生物 (true/false)。",
            "spawn-protection": "重生點保護半徑 (預設: 16)。非管理員無法在此範圍內放置或破壞方塊。",
            "sync-chunk-writes": "是否同步寫入區塊資料（true/false，預設: true）",
            "text-filtering-config": "文字過濾配置檔案路徑。用於過濾不當內容。",
            "text-filtering-version": "文字過濾規則版本（預設: 0）",
            "use-native-transport": "是否使用原生傳輸 (true/false)。可提升網路效能。",
            "view-distance": "視野距離 (4-32，預設: 10)。決定玩家能看到多遠的區塊。",
            "white-list": "是否啟用白名單 (true/false)。只有在白名單中的玩家才能加入。",
        }

    # 取得單一屬性的說明
    @staticmethod
    def get_property_description(property_name: str) -> str:
        """
        取得指定屬性的詳細說明文字
        Get detailed description text for a specific property

        Args:
            property_name (str): 屬性名稱

        Returns:
            str: 該屬性的說明文字，若屬性不存在則返回未知屬性訊息
        """
        descriptions = ServerPropertiesHelper.get_property_descriptions()
        return descriptions.get(property_name, f"未知屬性: {property_name}")

    # ====== 屬性分類與組織 ======
    # 取得屬性分類結構
    @staticmethod
    def get_property_categories() -> Dict[str, list]:
        """
        取得屬性按功能分類的組織結構，方便 UI 顯示分組
        Get property categories organized by functionality for convenient UI grouping display

        Args:
            None

        Returns:
            Dict[str, list]: 分類名稱對應屬性列表的字典
        """
        return {
            # 伺服器啟動與基本資訊
            "基本設定": [
                "server-port",
                "server-ip",
                "motd",
                "max-players",
                "gamemode",
                "difficulty",
                "hardcore",
                "pvp",
                "online-mode",
                "white-list",
                "enforce-whitelist",
                "force-gamemode",
            ],
            # 世界生成與地圖
            "世界設定": [
                "level-name",
                "level-seed",
                "level-type",
                "generator-settings",
                "generate-structures",
                "spawn-protection",
                "max-world-size",
            ],
            # 玩家行為與閒置
            "玩家設定": [
                "player-idle-timeout",
                "pause-when-empty-seconds",
                "allow-flight"
            ],
            # 生物生成
            "生物設定": [
                "spawn-monsters",
                "spawn-animals",
                "spawn-npcs"
            ],
            # 功能開關
            "功能設定": [
                "allow-nether",
                "enable-command-block",
                "enable-query",
                "enable-status",
                "enable-rcon",
                "debug",
                "enable-jmx-monitoring",
                "use-native-transport",
                "sync-chunk-writes",
            ],
            # 網路與安全
            "網路設定": [
                "network-compression-threshold",
                "rate-limit",
                "prevent-proxy-connections",
                "hide-online-players",
                "enforce-secure-profile",
                "log-ips",
            ],
            # 管理與權限
            "管理設定": [
                "op-permission-level",
                "function-permission-level",
                "rcon.port",
                "rcon.password",
                "query.port",
                "broadcast-console-to-ops",
                "broadcast-rcon-to-ops",
                "text-filtering-config",
                "text-filtering-version",
            ],
            # 效能與區塊
            "效能設定": [
                "view-distance",
                "simulation-distance",
                "entity-broadcast-range-percentage",
                "max-tick-time",
                "max-chained-neighbor-updates",
            ],
            # 資源包
            "資源包設定": [
                "resource-pack",
                "resource-pack-sha1",
                "require-resource-pack",
                "resource-pack-prompt",
                "resource-pack-id",
                "initial-enabled-packs",
                "initial-disabled-packs",
            ],
            # 進階/其他
            "進階設定": [
                "bug-report-link",
                "region-file-compression",
                "accepts-transfers"
            ],
        }

    # ====== 檔案操作與持久化 ======
    # 從檔案載入屬性配置
    @staticmethod
    def load_properties(file_path) -> Dict[str, str]:
        """
        從 server.properties 檔案讀取屬性配置並解析為字典
        Load property configuration from server.properties file and parse into dictionary

        Args:
            file_path: server.properties 檔案的路徑

        Returns:
            Dict[str, str]: 屬性名稱對應值的字典
        """
        properties = {}
        try:
            properties_file = Path(file_path)

            if properties_file.exists():
                with open(properties_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            properties[key.strip()] = value.strip()
        except Exception as e:
            LogUtils.error(f"載入 server.properties 失敗: {e}", "PropertiesHelper")

        return properties

    # 儲存屬性配置到檔案
    @staticmethod
    def save_properties(file_path, properties: Dict[str, str]):
        """
        將屬性字典儲存為 server.properties 檔案格式
        Save properties dictionary as server.properties file format

        Args:
            file_path: 要儲存的檔案路徑
            properties (Dict[str, str]): 屬性名稱對應值的字典

        Returns:
            None
        """
        try:
            properties_file = Path(file_path)

            with open(properties_file, "w", encoding="utf-8") as f:
                f.write("# Minecraft server properties\n")
                f.write("# Generated by Minecraft Server Manager\n\n")
                for key, value in properties.items():
                    f.write(f"{key}={value}\n")
        except Exception as e:
            LogUtils.error(f"儲存 server.properties 失敗: {e}", "PropertiesHelper")
