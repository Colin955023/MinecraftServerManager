#!/usr/bin/env python3
"""伺服器工具模組
整合了記憶體管理、屬性設定、伺服器檢測與操作等功能
Server Utilities Module
Integrates memory management, property settings, server detection, and operations
"""

import json
import re
from pathlib import Path

from ..models import ServerConfig
from . import UIUtils, get_logger, java_utils

logger = get_logger().bind(component="ServerUtils")

KB = 1024
MB = 1024 * 1024
GB = 1024 * 1024 * 1024


# ====== 記憶體工具類別 ======
class MemoryUtils:
    """記憶體工具類別，提供記憶體相關的解析和格式化功能
    Memory utilities class for memory-related parsing and formatting functions
    """

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> int | None:
        """解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數
        Parse Java memory settings, handling -Xmx and -Xms parameters uniformly

        Args:
            text: 包含記憶體設定的文本 (Text containing memory settings)
            setting_type: "Xmx" 或 "Xms" ("Xmx" or "Xms")

        Returns:
            int | None: 記憶體大小（MB），如果找不到則返回 None (Memory size in MB, or None if not found)

        """
        if not text or not isinstance(text, str):
            return None
        if not setting_type or setting_type not in ["Xmx", "Xms"]:
            return None

        pattern = rf"-{setting_type}(\d+)([mMgG]?)"
        match = re.search(pattern, text)
        if match:
            val, unit = match.groups()
            try:
                val = int(val)
                if unit and unit.lower() == "g":
                    return val * 1024
                return val
            except ValueError:
                return None
        return None

    @staticmethod
    def format_memory(memory_bytes: float) -> str:
        """格式化記憶體大小（位元組輸入）
        Format memory size (bytes input)
        """
        if memory_bytes < KB:
            return f"{memory_bytes:.1f} B"
        if memory_bytes < MB:
            return f"{memory_bytes / KB:.1f} KB"
        if memory_bytes < GB:
            return f"{memory_bytes / MB:.1f} MB"
        return f"{memory_bytes / GB:.1f} GB"

    @staticmethod
    def format_memory_mb(memory_mb: int) -> str:
        """格式化記憶體顯示
        Format memory display
        """
        if memory_mb >= 1024:
            return f"{memory_mb // 1024}G" if memory_mb % 1024 == 0 else f"{memory_mb / 1024:.1f}G"
        return f"{memory_mb}M"


# ====== Server Properties 說明助手  ======
class ServerPropertiesHelper:
    """server.properties 說明助手：提供屬性說明、分類、載入/儲存等功能。
    ServerPropertiesHelper: A helper class for server.properties, providing property descriptions, categories, loading/saving functions.
    """

    @staticmethod
    def get_property_descriptions() -> dict[str, str]:
        """取得所有 server.properties 屬性的中文說明字典 (依據官方 Wiki 更新)
        Get detailed Chinese descriptions for all server.properties attributes

        Returns:
            Dict[str, str]: 屬性名稱對應說明的字典 (Dictionary mapping property names to descriptions)

        """
        return {
            "accepts-transfers": "是否允許伺服器端接受以Transfer數據包作為登入請求的傳入連接。 (false/true)",
            "allow-flight": "是否允許玩家在生存模式下飛行。 (false/true) 若設為true，安裝了飛行模組的玩家可以飛行。",
            "allow-nether": "是否允許玩家進入地獄 (下界)。 (true/false) false - 玩家將無法通過地獄傳送門。",
            "broadcast-console-to-ops": "是否向所有線上OP傳送所執行命令的輸出。 (true/false)",
            "broadcast-rcon-to-ops": "是否向所有線上OP傳送通過RCON執行的命令的輸出。 (true/false)",
            "bug-report-link": "伺服器「報吿伺服器錯誤」的URL。 (字串) 顯示於玩家中斷連線畫面，引導玩家回報錯誤。",
            "difficulty": "定義伺服器的遊戲難度。 (peaceful/easy/normal/hard) 影響生物傷害、飢餓等。",
            "enable-code-of-conduct": "是否啟用行為準則顯示。 (false/true) true - 伺服器會查找並顯示 codeofconduct 資料夾中的行為準則檔案。",
            "enable-command-block": "是否啟用指令方塊。 (false/true) true - 允許指令方塊執行指令。",
            "enable-jmx-monitoring": "是否啟用 JMX 監控。 (false/true) 暴露 MBean 供效能監控，需額外 JVM 參數。",
            "enable-query": "是否允許使用GameSpy4協定的伺服器監聽器。 (false/true) 用於外部工具取得伺服器資訊。",
            "enable-rcon": "是否允許遠程訪問伺服器控制台。 (false/true) 注意 RCON 協定不加密，存在安全風險。",
            "enable-status": "使伺服器在伺服器列表中看起來是「線上」的。 (true/false) false - 伺服器將顯示為離線 (但在線玩家仍可見列表)。",
            "enforce-secure-profile": "要求玩家必須具有Mojang簽名的公鑰才能進入伺服器。 (true/false) true - 無簽名公鑰的玩家無法進入。",
            "enforce-whitelist": "在伺服器上強制執行白名單。 (false/true) true - 當伺服器重新載入白名單後，不在名單上的線上玩家會被踢出。",
            "entity-broadcast-range-percentage": "實體廣播範圍百分比 (10-1000)。控制實體距離玩家多近時才發送數據包。越高可見越遠但增加延遲。",
            "force-gamemode": "是否強制玩家加入時為預設遊戲模式。 (false/true) true - 每次加入都重設為預設模式。",
            "function-permission-level": "設定函數解析時的權限等級 (1-4)。 (預設: 2)",
            "gamemode": "定義新玩家的預設遊戲模式。 (survival/creative/adventure/spectator)",
            "generate-structures": "定義是否能生成結構 (如村莊)。 (true/false) 註：地牢等部分結構仍可能生成。",
            "generator-settings": "自訂世界的生成設定 (JSON格式)。用於超平坦或自訂世界類型。",
            "hardcore": "是否啟用極限模式。 (false/true) true - 死亡後自動轉為旁觀模式，難度鎖定為困難。",
            "hide-online-players": "是否在伺服器列表中隱藏線上玩家列表。 (false/true)",
            "initial-disabled-packs": "建立世界時要停用的數據包名稱 (逗號分隔)。",
            "initial-enabled-packs": "建立世界時要啟用的數據包名稱 (逗號分隔)。",
            "level-name": "世界名稱及其資料夾名。 (預設: world) 也可用於讀取現有存檔。",
            "level-seed": "世界種子碼。留空則隨機生成。",
            "level-type": "世界生成類型 ID。 (例如 minecraft:normal, minecraft:flat, minecraft:large_biomes, minecraft:amplified)",
            "log-ips": "是否在伺服器日誌中記錄玩家 IP。 (true/false)",
            "max-chained-neighbor-updates": "限制連鎖方塊更新的數量。 (預設: 1000000) 負數為無限制。",
            "max-players": "伺服器最大玩家數量 (0-2147483647)。超過此數量新玩家無法加入 (OP除外，若設定允許)。",
            "max-tick-time": "每個 tick 花費的最大毫秒數。 (0-2^63-1) 超過此值伺服器會強制關閉 (判定為崩潰)。設為 -1 可停用。",
            "max-world-size": "世界邊界的最大半徑 (1-29999984)。限制世界可探索範圍。",
            "motd": "伺服器列表顯示的訊息 (Message of the Day)。支援樣式代碼。",
            "network-compression-threshold": "網路壓縮閾值。 (預設: 256) 封包大於此位元組時進行壓縮。-1 為停用壓縮。",
            "online-mode": "是否啟用線上驗證 (正版驗證)。 (true/false) true - 需正版帳號登入。",
            "op-permission-level": "OP 管理員的預設權限等級 (1-4)。 1:繞過重生保護 2:單人作弊指令 3:多人管理指令 4:所有指令。",
            "pause-when-empty-seconds": "伺服器無人時自動停止計算的等待秒數。 (預設: 60) 負數為不停止。",
            "player-idle-timeout": "玩家閒置踢出時間 (分鐘)。 (預設: 0) 0 為不踢出。",
            "prevent-proxy-connections": "是否阻止代理/VPN 連接。 (false/true) 伺服器會驗證來源 IP 是否與 Mojang 驗證伺服器一致。",
            "pvp": "是否啟用玩家對戰 (PVP)。 (true/false) false - 玩家無法互相傷害。",
            "query.port": "設定 GameSpy4 查詢監聽端口。 (1-65534, 預設: 25565)",
            "rate-limit": "玩家發送數據包的速率限制。 (預設: 0) 0 為無限制。超過限制的玩家會被踢出。",
            "rcon.password": "RCON 遠程訪問的密碼。",
            "rcon.port": "RCON 遠程訪問的端口。 (1-65534, 預設: 25575)",
            "region-file-compression": "區域檔案壓縮演算法。 (deflate/lz4/none) deflate:最小體積, lz4:平衡, none:無壓縮。",
            "require-resource-pack": "是否強制玩家使用伺服器資源包。 (false/true) true - 拒絕資源包將被斷線。",
            "resource-pack": "資源包下載 URL (直連)。大小限制依版本而定 (1.18+ 為 250MB)。",
            "resource-pack-id": "資源包的 UUID。用於客戶端識別資源包快取。",
            "resource-pack-prompt": "自訂資源包提示訊息。 (僅在 require-resource-pack 為 true 時有效)",
            "resource-pack-sha1": "資源包的 SHA-1 雜湊值 (小寫十六進制)。用於驗證完整性。",
            "server-ip": "伺服器綁定 IP。 (建議留空) 留空則綁定所有可用介面。",
            "server-port": "伺服器監聽端口。 (1-65534, 預設: 25565)",
            "simulation-distance": "模擬距離 (3-32)。玩家周圍進行實體/作物更新的區塊半徑。",
            "spawn-monsters": "是否生成怪物。 (true/false)",
            "spawn-protection": "重生點保護半徑 (2x+1)。 (預設: 16) 非 OP 玩家無法破壞範圍內方塊。0 為停用。",
            "status-heartbeat-interval": "伺服器向客戶端發送心跳通知的間隔。 (預設: 0) 0 為停用。",
            "sync-chunk-writes": "是否同步寫入區塊檔案。 (true/false) true - 崩潰時較少掉檔，但可能影響效能。",
            "text-filtering-config": "文字過濾設定 (JSON URL)。 (通常留空)",
            "text-filtering-version": "文字過濾版本。 (0或1)",
            "use-native-transport": "是否使用 Linux 原生封包最佳化。 (true/false) 僅在 Linux 有效。",
            "view-distance": "伺服器發送給客戶端的區塊視距 (3-32)。影響客戶端能看到的範圍。",
            "white-list": "是否啟用白名單。 (false/true) true - 只有 whitelist.json 中的玩家可加入。",
            "management-server-enabled": "是否啟用管理伺服器協定 (Minecraft Management Protocol)。",
            "management-server-host": "管理伺服器監聽的主機 (預設 localhost)。",
            "management-server-port": "管理伺服器監聽的埠號 (預設 25585)。",
            "management-server-secret": "管理伺服器使用的密鑰。",
            "management-server-tls-enabled": "是否啟用管理伺服器 TLS 加密。",
            "management-server-tls-keystore": "TLS 金鑰庫路徑。",
            "management-server-tls-keystore-password": "TLS 金鑰庫密碼。",
            "management-server-allowed-origins": "管理伺服器允許的來源。",
        }

    @staticmethod
    def get_property_description(property_name: str) -> str:
        """取得指定屬性的詳細說明文字
        Get detailed description text for a specific property

        Args:
            property_name (str): 屬性名稱 (Property name)

        Returns:
            str: 該屬性的說明文字，若屬性不存在則返回未知屬性訊息 (Description text, or unknown message if not found)

        """
        descriptions = ServerPropertiesHelper.get_property_descriptions()
        return descriptions.get(property_name, f"未知屬性: {property_name}")

    @staticmethod
    def get_property_categories() -> dict[str, list]:
        """取得屬性按功能分類的組織結構，方便 UI 顯示分組
        Get property categories organized by functionality for convenient UI grouping display

        Returns:
            Dict[str, list]: 分類名稱對應屬性列表的字典 (Dictionary mapping category names to property lists)

        """
        return {
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
                "enable-status",
                "hide-online-players",
                "enable-code-of-conduct",
            ],
            "世界設定": [
                "level-name",
                "level-seed",
                "level-type",
                "generator-settings",
                "generate-structures",
                "spawn-protection",
                "max-world-size",
                "initial-enabled-packs",
                "initial-disabled-packs",
            ],
            "玩家設定": [
                "player-idle-timeout",
                "pause-when-empty-seconds",
                "allow-flight",
                "allow-nether",
            ],
            "生物設定": [
                "spawn-monsters",
            ],
            "功能設定": [
                "enable-command-block",
                "enable-query",
                "enable-rcon",
                "debug",
                "enable-jmx-monitoring",
                "use-native-transport",
                "sync-chunk-writes",
                "status-heartbeat-interval",
            ],
            "網路設定": [
                "network-compression-threshold",
                "rate-limit",
                "prevent-proxy-connections",
                "enforce-secure-profile",
                "log-ips",
            ],
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
            "管理伺服器設定": [
                "management-server-enabled",
                "management-server-host",
                "management-server-port",
                "management-server-secret",
                "management-server-tls-enabled",
                "management-server-tls-keystore",
                "management-server-tls-keystore-password",
                "management-server-allowed-origins",
            ],
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
            ],
            "進階設定": [
                "bug-report-link",
                "region-file-compression",
                "accepts-transfers",
            ],
        }

    @staticmethod
    def load_properties(file_path) -> dict[str, str]:
        """從 server.properties 檔案讀取屬性配置並解析為字典
        Load property configuration from server.properties file and parse into dictionary

        Args:
            file_path: server.properties 檔案的路徑 (Path to server.properties file)

        Returns:
            Dict[str, str]: 屬性名稱對應值的字典 (Dictionary mapping property names to values)

        """
        properties = {}
        try:
            properties_file = Path(file_path)

            if properties_file.exists():
                with open(properties_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            properties[key.strip()] = value.strip()
        except Exception as e:
            logger.exception(f"載入 server.properties 失敗: {e}")

        return properties

    @staticmethod
    def save_properties(file_path, properties: dict[str, str]):
        """將屬性字典儲存為 server.properties 檔案格式
        Save properties dictionary as server.properties file format

        Args:
            file_path: 要儲存的檔案路徑 (Path to save the file)
            properties (Dict[str, str]): 屬性名稱對應值的字典 (Dictionary mapping property names to values)

        """
        try:
            properties_file = Path(file_path)

            with open(properties_file, "w", encoding="utf-8") as f:
                f.write("# Minecraft server properties\n")
                f.write("# Generated by Minecraft Server Manager\n\n")
                f.writelines(f"{key}={value}\n" for key, value in properties.items())
        except Exception as e:
            logger.exception(f"儲存 server.properties 失敗: {e}")


# ====== 伺服器檢測工具類別 ======
class ServerDetectionUtils:
    """伺服器檢測工具類別，提供各種伺服器相關的檢測和驗證功能
    Server detection utility class providing various server-related detection and validation functions
    """

    @staticmethod
    def find_startup_script(server_path: Path) -> Path | None:
        """尋找伺服器啟動腳本
        Find server startup script

        Args:
            server_path (Path): 伺服器路徑 (Server path)

        Returns:
            Path | None: 啟動腳本路徑，若未找到則返回 None (Startup script path, or None if not found)

        """
        script_candidates = [
            "start_server.bat",
            "run.bat",
            "start.bat",
            "server.bat",
        ]

        for script_name in script_candidates:
            candidate_path = server_path / script_name
            if candidate_path.exists():
                return candidate_path

        return None

    # ====== 檔案與設定檢測  ======
    @staticmethod
    def get_missing_server_files(folder_path: Path) -> list:
        """檢查伺服器資料夾中缺少的關鍵檔案清單
        Check list of missing critical files in server folder

        Args:
            folder_path (Path): 伺服器資料夾路徑 (Server folder path)

        Returns:
            list: 缺少的檔案名稱清單 (List of missing file names)

        """
        missing = []
        # 主程式 JAR
        if not (folder_path / "server.jar").exists() and not any(
            (folder_path / f).exists()
            for f in [
                "minecraft_server.jar",
                "fabric-server-launch.jar",
                "fabric-server-launcher.jar",
            ]
        ):
            missing.append("server.jar 或同等主程式 JAR")
        # EULA
        if not (folder_path / "eula.txt").exists():
            missing.append("eula.txt")
        # server.properties
        if not (folder_path / "server.properties").exists():
            missing.append("server.properties")
        return missing

    @staticmethod
    def detect_eula_acceptance(server_path: Path) -> bool:
        """檢測 eula.txt 檔案中是否已設定 eula=true
        Detect if eula=true is set in eula.txt file

        Args:
            server_path (Path): 伺服器根目錄路徑 (Server root directory path)

        Returns:
            bool: 已接受 EULA 返回 True，否則返回 False (True if EULA accepted, else False)

        """
        eula_file = server_path / "eula.txt"
        if not eula_file.exists():
            return False

        try:
            with open(eula_file, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip().lower() == "eula":
                        return value.strip().lower() == "true"
            return False
        except Exception as e:
            logger.exception(f"讀取 eula.txt 失敗: {e}")
            return False

    # ====== 記憶體設定管理 ======
    @staticmethod
    def _process_startup_script(file_path: Path) -> tuple[list[str], bool, int | None, int | None]:
        """處理啟動腳本：移除 pause、添加 nogui、提取記憶體設定
        Process startup script: remove pause, add nogui, extract memory settings

        Args:
            file_path: 腳本檔案路徑 (Script file path)

        Returns:
            tuple: (script_lines, modified, max_memory_mb, min_memory_mb)
        """
        script_content = []
        modified = False
        max_m = None
        min_m = None

        with open(file_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_stripped = line.strip().lower()

                # 移除 pause 命令
                if line_stripped in ["pause", "@pause", "pause.", "@pause."]:
                    modified = True
                    continue

                # 檢查 Java 命令
                if "java" in line and ("-Xmx" in line or "-Xms" in line or ".jar" in line):
                    # 添加 nogui
                    if "nogui" not in line.lower():
                        line = line.rstrip("\r\n") + " nogui\n"
                        modified = True

                    # 提取記憶體設定（使用統一的工具）
                    if not max_m:
                        max_m = MemoryUtils.parse_memory_setting(line, "Xmx")
                    if not min_m:
                        min_m = MemoryUtils.parse_memory_setting(line, "Xms")

                script_content.append(line)

        return script_content, modified, max_m, min_m

    @staticmethod
    def _detect_memory_from_file(file_path: Path, is_script: bool = False) -> tuple[int | None, int | None]:
        """從單個檔案偵測記憶體設定（統一接口）
        Detect memory settings from a single file (unified interface)

        Args:
            file_path: 要掃描的檔案路徑 (File path to scan)
            is_script: 是否為啟動腳本 (Whether it's a startup script)

        Returns:
            tuple[int | None, int | None]: (max_memory_mb, min_memory_mb)
        """
        if not file_path.exists():
            return None, None

        try:
            if is_script:
                # 處理啟動腳本（可能修改檔案）
                script_content, modified, max_m, min_m = ServerDetectionUtils._process_startup_script(file_path)

                # 如果修改了腳本，寫回檔案
                if modified:
                    try:
                        with open(file_path, "w", encoding="utf-8") as fw:
                            fw.writelines(script_content)
                        logger.info(f"已優化啟動腳本: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"無法更新腳本 {file_path}: {e}")

                return max_m, min_m
            # 處理參數檔（只讀取）
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            max_m = MemoryUtils.parse_memory_setting(content, "Xmx")
            min_m = MemoryUtils.parse_memory_setting(content, "Xms")
            return max_m, min_m

        except Exception as e:
            logger.debug(f"讀取記憶體檔案失敗 {file_path}: {e}")
            return None, None

    @staticmethod
    def update_forge_user_jvm_args(server_path: Path, config: ServerConfig) -> None:
        """更新新版 Forge 的 user_jvm_args.txt 檔案，設定記憶體參數
        Update user_jvm_args.txt file for newer Forge versions with memory parameters

        Args:
            server_path (Path): 伺服器根目錄路徑 (Server root directory path)
            config (ServerConfig): 伺服器配置物件 (Server configuration object)

        """
        user_jvm_args_path = server_path / "user_jvm_args.txt"
        lines = []
        if config.memory_min_mb:
            lines.append(f"-Xms{config.memory_min_mb}M\n")
        if config.memory_max_mb:
            lines.append(f"-Xmx{config.memory_max_mb}M\n")
        try:
            with open(user_jvm_args_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.exception(f"寫入失敗: {e}")
            UIUtils.show_error(
                "寫入失敗",
                f"無法更新 {user_jvm_args_path} 檔案。請檢查權限或磁碟空間。錯誤: {e}",
            )

    @staticmethod
    def detect_memory_from_sources(server_path: Path, config: ServerConfig) -> None:
        """檢測記憶體大小 - 簡化版本
        Detect memory size - Simplified version

        Args:
            server_path (Path): 伺服器根目錄路徑 (Server root directory path)
            config (ServerConfig): 伺服器配置物件 (Server configuration object)
        """
        # 優先級順序掃描
        memory_sources = [
            # 高優先級: Forge 專用參數檔
            [("user_jvm_args.txt", False), ("jvm.args", False)],
            # 中優先級: 標準啟動腳本
            [("start_server.bat", True), ("start.bat", True)],
        ]

        max_mem = None
        min_mem = None

        # 按優先級掃描
        for source_group in memory_sources:
            for source_file, is_script in source_group:
                fpath = server_path / source_file
                max_m, min_m = ServerDetectionUtils._detect_memory_from_file(fpath, is_script)

                if max_m is not None:
                    max_mem = max_m
                if min_m is not None:
                    min_mem = min_m

                if max_mem is not None and min_mem is not None:
                    logger.debug(f"從 {source_file} 偵測到記憶體: {min_mem}M - {max_mem}M")
                    break

            if max_mem is not None and min_mem is not None:
                break

        # 低優先級: 掃描其他啟動腳本
        if max_mem is None or min_mem is None:
            for script in server_path.glob("*.bat"):
                if script.name in ["start_server.bat", "start.bat"]:
                    continue
                max_m, min_m = ServerDetectionUtils._detect_memory_from_file(script, is_script=True)
                if max_m:
                    max_mem = max_mem or max_m
                if min_m:
                    min_mem = min_mem or min_m
                if max_mem and min_mem:
                    break

        # 應用到配置
        if max_mem is not None:
            config.memory_max_mb = max_mem
            config.memory_min_mb = min_mem if min_mem is not None else max_mem
        elif min_mem is not None:
            config.memory_max_mb = min_mem
            config.memory_min_mb = min_mem

        # Forge 特殊處理
        if hasattr(config, "loader_type") and str(getattr(config, "loader_type", "")).lower() == "forge":
            ServerDetectionUtils.update_forge_user_jvm_args(server_path, config)

    @staticmethod
    def detect_server_type(server_path: Path, config: "ServerConfig", print_result: bool = True) -> None:
        """檢測伺服器類型和版本 - 統一的偵測邏輯
        Detect server type and version - Unified detection logic.

        Args:
            server_path (Path): 伺服器路徑 (Server path)
            config (ServerConfig): 伺服器配置 (Server configuration)
            print_result (bool): 是否列印結果 (Whether to print results)

        """
        try:
            jar_files = list(server_path.glob("*.jar"))
            jar_names = [f.name.lower() for f in jar_files]

            detection_source = {}  # 紀錄偵測來源

            fabric_files = ["fabric-server-launch.jar", "fabric-server-launcher.jar"]
            if any((server_path / f).exists() for f in fabric_files):
                config.loader_type = "fabric"
                detected_file = next(f for f in fabric_files if (server_path / f).exists())
                detection_source["loader_type"] = f"檔案 {detected_file}"
            elif (server_path / "libraries/net/minecraftforge/forge").is_dir():
                config.loader_type = "forge"
                detection_source["loader_type"] = "目錄 libraries/net/minecraftforge/forge"
            elif any("forge" in name for name in jar_names):
                config.loader_type = "forge"
                detected_file = next(name for name in jar_names if "forge" in name)
                detection_source["loader_type"] = f"JAR 檔案 {detected_file}"
            elif any(name in ("server.jar", "minecraft_server.jar") for name in jar_names):
                config.loader_type = "vanilla"
                detected_file = next(name for name in jar_names if name in ("server.jar", "minecraft_server.jar"))
                detection_source["loader_type"] = f"JAR 檔案 {detected_file}"
            else:
                config.loader_type = "unknown"
                detection_source["loader_type"] = "無法判斷"

            ServerDetectionUtils.detect_loader_and_version_from_sources(
                server_path,
                config,
                config.loader_type,
                detection_source,
            )

            ServerDetectionUtils.detect_memory_from_sources(server_path, config)

            detected_main_jar = ServerDetectionUtils.detect_main_jar_file(server_path, config.loader_type, config)
            config.eula_accepted = ServerDetectionUtils.detect_eula_acceptance(server_path)

            if print_result:
                logger.info(f"偵測結果 - 路徑: {server_path.name}")
                logger.info(f"  載入器: {config.loader_type} (來源: {detection_source.get('loader_type', '未知')})")
                if detection_source.get("loader_version"):
                    logger.info(f"  MC版本: {config.minecraft_version} (來源: {detection_source['mc_version']})")
                    logger.info(f"  載入器版本: {config.loader_version} (來源: {detection_source['loader_version']})")
                else:
                    logger.info(f"  MC版本: {config.minecraft_version}")
                logger.info(f"  主要JAR/啟動檔: {detected_main_jar}")  # 新增顯示偵測到的啟動檔
                logger.info(f"  EULA狀態: {'已接受' if config.eula_accepted else '未接受'}")
                if hasattr(config, "memory_max_mb") and config.memory_max_mb:
                    if hasattr(config, "memory_min_mb") and config.memory_min_mb:
                        logger.info(f"  記憶體: 最小 {config.memory_min_mb}MB, 最大 {config.memory_max_mb}MB")
                    else:
                        logger.info(f"  記憶體: 0-{config.memory_max_mb}MB")
                else:
                    logger.info("  記憶體: 未設定")

        except Exception as e:
            logger.exception(f"檢測伺服器類型失敗: {e}")

    @staticmethod
    def is_valid_server_folder(folder_path: Path) -> bool:
        """檢查是否為有效的 Minecraft 伺服器資料夾
        Check if the folder is a valid Minecraft server directory.

        Args:
            folder_path (Path): 伺服器資料夾路徑 (Server folder path)

        Returns:
            bool: 是否為有效的伺服器資料夾 (True if valid server folder, else False)

        """
        if not folder_path.is_dir():
            return False

        server_jars = [
            "server.jar",
            "minecraft_server.jar",
            "fabric-server-launch.jar",
            "fabric-server-launcher.jar",
        ]
        if any((folder_path / jar_name).exists() for jar_name in server_jars):
            return True

        for file in folder_path.glob("*.jar"):
            jar_name = file.name.lower()
            if any(pattern in jar_name for pattern in ["forge", "server", "minecraft"]):
                return True

        server_indicators = ["server.properties", "eula.txt"]
        return bool(any((folder_path / indicator).exists() for indicator in server_indicators))

    @staticmethod
    def _get_latest_log_file(server_path: Path) -> Path | None:
        """取得最新的日誌檔，優先級: 時間戳 > 標準名稱
        Get the latest log file with priority on timestamp

        Args:
            server_path: 伺服器路徑 (Server path)

        Returns:
            最新的日誌檔路徑，或 None (Latest log file path, or None)
        """
        log_candidates = ["latest.log", "server.log", "debug.log"]
        logs_dir = server_path / "logs"

        if not logs_dir.is_dir():
            return None

        found_logs = []
        for name in log_candidates:
            fpath = logs_dir / name
            if fpath.exists():
                found_logs.append(fpath)

        if not found_logs:
            # Fallback: 掃描所有 .log 檔案
            found_logs = list(logs_dir.glob("*.log"))

        if not found_logs:
            return None

        # 按修改時間排序，最新的優先
        found_logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        logger.debug(f"選擇日誌檔: {found_logs[0].name}")
        return found_logs[0]

    @staticmethod
    def detect_loader_and_version_from_sources(
        server_path: Path,
        config,
        loader: str,
        detection_source: dict | None = None,
    ) -> None:
        """從多種來源偵測 Fabric/Forge 載入器與 Minecraft 版本
        Detect Fabric/Forge loader and Minecraft version from multiple sources

        Args:
            server_path (Path): 伺服器路徑 (Server path)
            config: 伺服器配置物件 (Server configuration object)
            loader (str): 載入器類型 (Loader type)
            detection_source (dict, optional): 偵測來源字典，用於記錄版本偵測來源

        """
        if detection_source is None:
            detection_source = {}

        # ---------- 共用小工具 ----------
        def is_unknown(value: str | None) -> bool:
            return value in (None, "", "unknown", "Unknown", "無")

        def set_if_unknown(attr_name: str, value: str):
            if is_unknown(getattr(config, attr_name)):
                setattr(config, attr_name, value)

        def first_match(content: str, patterns: list[str]) -> str | None:
            for pat in patterns:
                m = re.search(pat, content, re.IGNORECASE)
                if m:
                    return m.group(1)
            return None

        def detect_from_logs():
            """從日誌檔偵測載入器和 Minecraft 版本 - 改進版本
            Detect loader and Minecraft version from logs - Improved version
            """
            log_file = ServerDetectionUtils._get_latest_log_file(server_path)

            if not log_file or not log_file.exists():
                return

            loader_patterns = {
                "fabric": [
                    r"Fabric Loader (\d+\.\d+\.\d+)",
                    r"FabricLoader/(\d+\.\d+\.\d+)",
                    r"fabric-loader (\d+\.\d+\.\d+)",
                    r"Loading Fabric (\d+\.\d+\.\d+)",
                ],
                "forge": [
                    r"fml.forgeVersion, (\d+\.\d+\.\d+)",
                    r"Forge Mod Loader version (\d+\.\d+\.\d+)",
                    r"MinecraftForge v(\d+\.\d+\.\d+)",
                    r"Forge (\d+\.\d+\.\d+)",
                    r"forge-(\d+\.\d+\.\d+)",
                ],
            }
            mc_patterns = [
                r"Starting minecraft server version (\d+\.\d+(?:\.\d+)?)",
                r"Minecraft (\d+\.\d+(?:\.\d+)?)",
                r"Server version: (\d+\.\d+(?:\.\d+)?)",
            ]

            try:
                with open(log_file, encoding="utf-8", errors="ignore") as f:
                    # 讀取前 2000 行以加快速度
                    content = "".join(f.readlines()[:2000])
            except Exception as e:
                logger.debug(f"讀取日誌檔失敗 {log_file}: {e}")
                return

            if loader in loader_patterns:
                v = first_match(content, loader_patterns[loader])
                if v:
                    set_if_unknown("loader_version", v)
                    if detection_source:
                        detection_source["loader_version"] = f"日誌檔 {log_file.name}"

            mc_ver = first_match(content, mc_patterns)
            if mc_ver:
                set_if_unknown("minecraft_version", mc_ver)
                if detection_source and "mc_version" not in detection_source:
                    detection_source["mc_version"] = f"日誌檔 {log_file.name}"

        def detect_from_forge_lib():
            forge_dir = server_path / "libraries" / "net" / "minecraftforge" / "forge"
            if not forge_dir.is_dir():
                return
            subdirs = [d for d in forge_dir.iterdir() if d.is_dir()]
            if not subdirs:
                return

            folder = subdirs[0].name
            mc, forge_ver = ServerDetectionUtils._extract_version_from_forge_path(folder)
            if mc and forge_ver:
                set_if_unknown("minecraft_version", mc)
                set_if_unknown("loader_version", forge_ver)
            else:
                # Fallback: 嘗試從 JAR 檔案名稱解析
                for jar in subdirs[0].glob("*.jar"):
                    m2 = re.match(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?)-.*\.jar", jar.name)
                    if m2:
                        mc2, forge_ver2 = m2.groups()
                        set_if_unknown("minecraft_version", mc2)
                        set_if_unknown("loader_version", forge_ver2)
                        break

        def detect_from_jars():
            for jar in server_path.glob("*.jar"):
                name_lower = jar.name.lower()

                if is_unknown(config.loader_type):
                    if "fabric" in name_lower:
                        config.loader_type = "fabric"
                    elif "forge" in name_lower:
                        config.loader_type = "forge"
                    else:
                        config.loader_type = "vanilla"

                m = re.search(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?).*\.jar", jar.name)
                if m:
                    mc, forge_ver = m.groups()
                    set_if_unknown("minecraft_version", mc)
                    set_if_unknown("loader_version", forge_ver)

                if (
                    not is_unknown(config.loader_type)
                    and not is_unknown(config.loader_version)
                    and not is_unknown(config.minecraft_version)
                ):
                    break

        def detect_from_version_json():
            fp = server_path / "version.json"
            if not fp.exists():
                return
            try:
                with open(fp, encoding="utf-8") as f:
                    data = json.load(f)
                if "id" in data:
                    set_if_unknown("minecraft_version", data["id"])
                if "forgeVersion" in data:
                    set_if_unknown("loader_version", data["forgeVersion"])
            except Exception as e:
                logger.exception(f"解析 version.json 失敗 {fp}: {e}")

        detect_from_logs()

        if loader == "fabric" and is_unknown(config.loader_version):
            config.loader_version = "unknown"

        if loader == "forge":
            detect_from_forge_lib()

        detect_from_jars()
        detect_from_version_json()

        if is_unknown(config.loader_type) and is_unknown(config.loader_type):
            config.loader_type = "vanilla"

    @staticmethod
    def _extract_version_from_forge_path(path_str: str) -> tuple[str | None, str | None]:
        """從 Forge 路徑提取 MC 版本和 Forge 版本
        Extract Minecraft and Forge versions from Forge path string

        Args:
            path_str: Forge 版本資料夾名稱，格式如 "1.20.1-47.3.29"
                    Forge version folder name, format like "1.20.1-47.3.29"

        Returns:
            tuple[str | None, str | None]: (minecraft_version, forge_version)

        """
        m = re.match(r"(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?)", path_str)
        if m:
            groups = m.groups()
            return (groups[0], groups[1])
        return None, None

    @staticmethod
    def find_forge_args_file(server_path: Path, server_config=None) -> Path | None:
        """尋找 Forge 的 win_args.txt 啟動參數檔
        Find Forge's win_args.txt startup argument file.

        Args:
            server_path: 伺服器根目錄
            server_config: 伺服器配置物件 (用於精確查找)

        Returns:
            找到的 win_args.txt 路徑，否則 None
        """
        forge_lib_dir = server_path / "libraries" / "net" / "minecraftforge" / "forge"
        if not forge_lib_dir.is_dir():
            return None

        # 1. 精確查找 (如果已知版本)
        if (
            server_config
            and server_config.minecraft_version
            and server_config.loader_version
            and server_config.minecraft_version.lower() != "unknown"
            and server_config.loader_version.lower() != "unknown"
        ):
            folder_name = f"{server_config.minecraft_version}-{server_config.loader_version}"
            args_path = forge_lib_dir / folder_name / "win_args.txt"
            if args_path.exists():
                return args_path

        # 2. 模糊查找 (搜尋所有並取最新的)
        arg_files = list(forge_lib_dir.rglob("win_args.txt"))
        if arg_files:
            arg_files.sort(key=lambda p: len(p.parts), reverse=True)
            return arg_files[0]
        return None

    @staticmethod
    def _parse_forge_args_file(args_path: Path) -> dict[str, str | list[str] | None]:
        """解析 Forge win_args.txt，提取關鍵啟動訊息
        Parse Forge win_args.txt and extract key startup information.

        Returns:
            包含以下可能的鍵值對：
            - 'jar': 直接 -jar 指定的 JAR 檔案 (Modern 1.21.11+)
            - 'bootstraplauncher': BootstrapLauncher 類別 (1.20.1)
            - 'forge_libraries': Forge 相關 library JAR 列表
            - 'minecraft_version': 從路徑解析出的 MC 版本
            - 'forge_version': 從路徑解析出的 Forge 版本
        """
        result: dict[str, str | list[str] | None] = {
            "jar": None,
            "bootstraplauncher": None,
            "forge_libraries": [],
            "minecraft_version": None,
            "forge_version": None,
        }

        try:
            with open(args_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # 檢查是否為新式 -jar 格式 (1.21.11+)
            jar_match = re.search(r"-jar\s+([^\s]+\.jar)", content, re.IGNORECASE)
            if jar_match:
                result["jar"] = jar_match.group(1)
                logger.info(f"偵測到 Modern Forge -jar 格式: {result['jar']}")

            # 檢查是否為 BootstrapLauncher 格式 (1.20.1)
            bootstrap_match = re.search(r"cpw\.mods\.bootstraplauncher\.BootstrapLauncher", content, re.IGNORECASE)
            if bootstrap_match:
                result["bootstraplauncher"] = "cpw.mods.bootstraplauncher.BootstrapLauncher"
                logger.info("偵測到 BootstrapLauncher 格式 (1.20.1 類型)")

            # 提取所有關鍵的 Forge 相關 library
            # 優先順序：forge > fmlloader > minecraft server > 其他
            forge_libs = re.findall(
                r"libraries[\\/].*?(?:forge|fmlloader|minecraft[/\\]server).*?\.jar", content, re.IGNORECASE
            )
            if forge_libs:
                forge_libs_list: list[str] = list(set(forge_libs))
                result["forge_libraries"] = forge_libs_list
                logger.debug(f"找到 {len(forge_libs_list)} 個 Forge libraries")

            # ✨ 新增: 從路徑提取版本號
            # win_args.txt 路徑格式: libraries/net/minecraftforge/forge/{mc_version}-{forge_version}/win_args.txt
            parent_dir = args_path.parent.name  # e.g., "1.20.1-47.3.29"
            mc_ver, forge_ver = ServerDetectionUtils._extract_version_from_forge_path(parent_dir)
            if mc_ver and forge_ver:
                result["minecraft_version"] = mc_ver
                result["forge_version"] = forge_ver
                logger.info(f"從 Forge 目錄路徑提取版本: MC={mc_ver}, Forge={forge_ver}")

        except Exception as e:
            logger.warning(f"解析 win_args.txt 失敗: {e}")

        return result

    @staticmethod
    def detect_main_jar_file(server_path: Path, loader_type: str, server_config: ServerConfig | None = None) -> str:
        """偵測主伺服器 JAR 檔案名稱，根據載入器類型（Forge/Fabric/Vanilla）返回適當的 JAR 名稱
        Detects the main server JAR file name based on the loader type (Forge/Fabric/Vanilla) and returns the appropriate JAR name.

        Args:
            server_path (Path): 伺服器路徑 (Server path)
            loader_type (str): 載入器類型 (Loader type)
            server_config (ServerConfig | None): 伺服器配置物件，用於優化查找路徑

        Returns:
            str: 主伺服器 JAR 檔案名稱 (Main server JAR file name)

        """
        logger.debug(f"server_path={server_path}")
        logger.debug(f"loader_type={loader_type}")

        loader_type_lc = loader_type.lower() if loader_type else ""
        jar_files = [f.name for f in server_path.glob("*.jar")]
        jar_files_lower = [f.lower() for f in jar_files]

        if loader_type_lc == "forge":
            # 使用共用的查找邏輯
            args_path = ServerDetectionUtils.find_forge_args_file(server_path, server_config)

            if args_path:
                # 解析參數檔
                args_info = ServerDetectionUtils._parse_forge_args_file(args_path)

                # 情況 1: Modern 1.21.11+ 使用 -jar 格式
                jar_val = args_info.get("jar")
                if jar_val and isinstance(jar_val, str):
                    return jar_val

                # 情況 2+3: 嘗試從參數檔中尋找 forge library JAR
                # (無論是 BootstrapLauncher 還是其他格式，優先返回具體的 JAR)
                libs_val = args_info.get("forge_libraries")
                if libs_val and isinstance(libs_val, list) and libs_val:
                    # 優先選擇名稱中包含 "server" 的 JAR，或最長的那個
                    candidates = [lib for lib in libs_val if "server" in lib.lower()]
                    if not candidates:
                        candidates = sorted(libs_val, key=len, reverse=True)
                    if candidates:
                        logger.info(f"從參數檔解析出 Forge JAR: {candidates[0]}")
                        return candidates[0]

                # 情況 4: 如果 BootstrapLauncher 但沒有找到具體 JAR，返回參數檔本身
                bootstrap_val = args_info.get("bootstraplauncher")
                if bootstrap_val:
                    result = f"@{args_path.relative_to(server_path)}"
                    logger.info(f"BootstrapLauncher 模式，使用參數檔啟動: {result}")
                    return result

                # 如果無法解析，返回參數檔本身作為 fallback
                result = f"@{args_path.relative_to(server_path)}"
                logger.info(f"使用參數檔作為主要執行檔: {result}")
                return result

            mc_ver = None
            forge_ver = None
            for fname in jar_files:
                m = re.match(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?).*\\.jar", fname)
                if m:
                    mc_ver, forge_ver = m.group(1), m.group(2)
                    break

            if mc_ver and forge_ver:
                for fname, lower in zip(jar_files, jar_files_lower):
                    if "forge" in lower and mc_ver in lower and forge_ver in lower and "installer" not in lower:
                        logger.info(f"偵測到 Forge JAR (版本匹配): {fname}")
                        return fname

            for fname, lower in zip(jar_files, jar_files_lower):
                if "forge" in lower and "installer" not in lower:
                    logger.info(f"偵測到 Forge JAR (模糊匹配): {fname}")
                    return fname

            for fname, lower in zip(jar_files, jar_files_lower):
                if "installer" not in lower and lower != "server.jar" and "minecraft_server" not in lower:
                    logger.info(f"偵測到自定義主程式 JAR: {fname}")
                    return fname

            if (server_path / "server.jar").exists():
                logger.info("回退使用 server.jar")
                return "server.jar"

            if (server_path / "minecraft_server.jar").exists():
                logger.info("回退使用 minecraft_server.jar")
                return "minecraft_server.jar"

            if jar_files:
                logger.info(f"回退使用資料夾中第一個發現的 JAR: {jar_files[0]}")
                return jar_files[0]

            logger.info("未發現可用 JAR，最終回退: server.jar")
            return "server.jar"

        if loader_type_lc == "fabric":
            for candidate in [
                "fabric-server-launch.jar",
                "fabric-server-launcher.jar",
                "server.jar",
            ]:
                if (server_path / candidate).exists():
                    logger.info(f"偵測到 Fabric 啟動 JAR: {candidate}")
                    return candidate
            logger.info("未發現 Fabric 啟動 JAR，回退: server.jar")
            return "server.jar"

        for candidate in ["server.jar", "minecraft_server.jar"]:
            if (server_path / candidate).exists():
                logger.info(f"偵測到原版 JAR: {candidate}")
                return candidate
        logger.info("未發現原版 JAR，回退: server.jar")
        return "server.jar"


# ====== 伺服器操作工具類別 Server Operations ======
class ServerOperations:
    """伺服器操作工具類別
    Server operations utility class
    """

    @staticmethod
    def get_status_text(is_running: bool) -> tuple:
        """獲取狀態文字和顏色
        Get status text and color
        """
        return ("🟢 狀態: 運行中", "green") if is_running else ("🔴 狀態: 已停止", "red")

    @staticmethod
    def graceful_stop_server(server_manager, server_name: str) -> bool:
        """優雅停止伺服器（先嘗試 stop 命令，失敗則強制停止）
        Gracefully stop the server (try 'stop' command first, force stop if failed)
        """
        try:
            # 先嘗試使用 stop 命令
            command_success = server_manager.send_command(server_name, "stop")
            # 如果命令成功，返回 True；否則使用強制停止
            return command_success or server_manager.stop_server(server_name)
        except Exception as e:
            logger.exception(f"停止伺服器失敗: {e}")
            return False


# ====== 伺服器指令工具類別 ======
class ServerCommands:
    """伺服器指令工具類別
    Server commands utility class
    """

    @staticmethod
    def build_java_command(server_config, return_list=False) -> list | str:
        """構建 Java 啟動命令（統一邏輯）
        Build Java launch command (unified logic)

        Args:
            server_config: 伺服器配置對象
            return_list: 是否返回列表格式 (True) 或字符串格式 (False)

        Returns:
            list or str: Java 啟動命令 (Java launch command)
        """
        server_path = Path(server_config.path)
        loader_type = str(server_config.loader_type or "").lower()
        memory_min = max(512, server_config.memory_min_mb) if server_config.memory_min_mb else 1024
        memory_max = max(memory_min, server_config.memory_max_mb) if server_config.memory_max_mb else 2048

        java_exe = java_utils.get_best_java_path(str(getattr(server_config, "minecraft_version", ""))) or "java"
        java_exe = java_exe.replace("javaw.exe", "java.exe")

        # 偵測主要 JAR/參數檔
        main_jar = ServerDetectionUtils.detect_main_jar_file(server_path, loader_type, server_config)

        # ============ 根據 loader_type 構建命令 ============

        # Forge 伺服器：檢查啟動參數檔格式
        if loader_type == "forge" and main_jar.startswith("@"):
            # 使用參數檔啟動 (1.20.1 類型或需要參數檔的版本)
            cmd_list = [java_exe, main_jar, "nogui"]
            result_cmd = f"{java_exe} {main_jar} nogui"

        # Vanilla 或 Fabric 伺服器 / 或 Forge Modern 版本
        else:
            cmd_list = [
                java_exe,
                f"-Xms{memory_min}M",
                f"-Xmx{memory_max}M",
                "-jar",
                main_jar,
                "nogui",
            ]

            # 構建字符串版本，處理路徑中有空格的情況
            if " " in java_exe and not (java_exe.startswith('"') and java_exe.endswith('"')):
                java_exe_quoted = f'"{java_exe}"'
            else:
                java_exe_quoted = java_exe

            if " " in main_jar and not (main_jar.startswith('"') and main_jar.endswith('"')):
                main_jar_quoted = f'"{main_jar}"'
            else:
                main_jar_quoted = main_jar

            result_cmd = f"{java_exe_quoted} -Xms{memory_min}M -Xmx{memory_max}M -jar {main_jar_quoted} nogui"

        if return_list:
            return cmd_list
        return result_cmd
