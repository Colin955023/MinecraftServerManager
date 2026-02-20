"""伺服器工具模組
整合了記憶體管理、屬性設定、伺服器檢測與操作等功能
Server Utilities Module
Integrates memory management, property settings, server detection, and operations
"""

import re
import types
from pathlib import Path

from ..models import ServerConfig
from . import JavaUtils, PathUtils, UIUtils, get_logger

logger = get_logger().bind(component="ServerUtils")

KB = 1024
MB = 1024 * 1024
GB = 1024 * 1024 * 1024

# Loader detection constants
FABRIC_JAR_NAMES = [
    "fabric-server-launch.jar",
    "fabric-server-launcher.jar",
]
FORGE_LIBRARY_PATH = "libraries/net/minecraftforge/forge"
FABRIC_MIN_MC_VERSION = (1, 14)


# ====== 記憶體工具類別 ======
class MemoryUtils:
    """記憶體工具類別，提供記憶體相關的解析和格式化功能"""

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> int | None:
        """解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數"""
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
    def format_memory_mb(memory_mb: int, compact: bool = True) -> str:
        """格式化記憶體大小（MB），根據大小自動選擇單位顯示，並提供簡潔或詳細格式選項"""
        if compact:
            # 簡潔格式：用於配置顯示
            if memory_mb >= 1024:
                return f"{memory_mb // 1024}G" if memory_mb % 1024 == 0 else f"{memory_mb / 1024:.1f}G"
            return f"{memory_mb}M"
        # 詳細格式：用於監控顯示
        if memory_mb >= 1024:
            return f"{memory_mb / 1024:.1f} GB"
        return f"{memory_mb:.1f} MB"


# ====== Server Properties 說明助手  ======
class ServerPropertiesHelper:
    """server.properties 說明助手：提供屬性說明、分類、載入/儲存等功能。"""

    # 類別級別的屬性描述緩存，避免重複構建
    _property_descriptions_cache: dict[str, str] | None = None

    @classmethod
    def get_property_descriptions(cls) -> types.MappingProxyType:
        """取得所有屬性說明的不可修改視圖（帶快取）

        Returns:
            types.MappingProxyType: 屬性名稱對應說明文字的不可修改視圖
        """
        if cls._property_descriptions_cache is not None:
            return types.MappingProxyType(cls._property_descriptions_cache)

        cls._property_descriptions_cache = {
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
            "motd": "伺服器列表顯示的訊息。支援樣式代碼。",
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
            "management-server-enabled": "是否啟用管理伺服器協定。",
            "management-server-host": "管理伺服器監聽的主機 (預設 localhost)。",
            "management-server-port": "管理伺服器監聽的埠號 (預設 25585)。",
            "management-server-secret": "管理伺服器使用的密鑰。",
            "management-server-tls-enabled": "是否啟用管理伺服器 TLS 加密。",
            "management-server-tls-keystore": "TLS 金鑰庫路徑。",
            "management-server-tls-keystore-password": "TLS 金鑰庫密碼。",
            "management-server-allowed-origins": "管理伺服器允許的來源。",
        }
        return types.MappingProxyType(cls._property_descriptions_cache)

    @staticmethod
    def get_property_description(property_name: str) -> str:
        """取得指定屬性的詳細說明文字

        Args:
            property_name: 屬性名稱

        Returns:
            str: 屬性說明文字，若屬性未知則返回提示訊息
        """
        descriptions = ServerPropertiesHelper.get_property_descriptions()
        return descriptions.get(property_name, f"未知屬性: {property_name}")

    @staticmethod
    def get_property_categories() -> dict[str, list]:
        """取得屬性按功能分類的組織結構，方便 UI 顯示分組"""
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
        """從 server.properties 檔案讀取屬性配置並解析為字典"""
        properties = {}
        try:
            properties_file = Path(file_path)
            content = PathUtils.read_text_file(properties_file)

            def _unescape_property(token: str) -> str:
                """還原 Java properties 風格的跳脫字元（鍵/值）。

                處理以下跳脫序列：
                - \\: (:), \\= (=), \\  (空格), \\\\ (\\)
                - \\t (制表符), \\n (換行), \\r (回車), \\f (換頁)
                """
                if token is None:
                    return ""
                token = token.strip()
                # 還原常見的跳脫字元
                result = token
                result = result.replace("\\t", "\t")  # 制表符
                result = result.replace("\\n", "\n")  # 換行
                result = result.replace("\\r", "\r")  # 回車
                result = result.replace("\\f", "\f")  # 換頁
                return re.sub(r"\\([:=\s\\])", lambda m: m.group(1), result)

            if content:
                for line in content.splitlines():
                    line = line.strip()
                    # 忽略空行和註解行（以 # 開頭）
                    if not line or line.startswith("#"):
                        continue

                    # 使用正則表達式找到第一個未被反斜線轉義的 = 或 : 作為分隔符
                    match = re.search(r"(?<!\\)(=|:)", line)
                    if not match:
                        continue

                    key_part = line[: match.start()]
                    value_part = line[match.end() :]

                    key = _unescape_property(key_part)
                    value = _unescape_property(value_part)

                    if key and key.strip():
                        properties[key] = value
        except Exception as e:
            logger.exception(f"載入 server.properties 失敗: {e}")

        return properties

    @staticmethod
    def save_properties(file_path, properties: dict[str, str]):
        """將屬性字典儲存為 server.properties 檔案格式"""
        try:
            properties_file = Path(file_path)
            lines = ["# Minecraft server properties", "# Generated by Minecraft Server Manager", ""]

            def _escape_property_value(raw_value: str) -> str:
                """跳脫 Java properties 屬性值中的特殊字元。

                處理以下字元：
                - \\ -> \\\\
                - \n -> \\n
                - \r -> \\r
                - \t -> \\t
                - \f -> \\f
                - : -> \\: (需正確處理已跳脫的反斜線)
                - = -> \\= (前導 = 號)
                - 前導空格 -> \\
                """
                if not raw_value:
                    return raw_value

                result: list[str] = []

                for i, ch in enumerate(raw_value):
                    if ch == "\\":
                        result.append(ch)
                        continue

                    # 處理需要跳脫的字元
                    if ch == ":" or ch == "=":
                        backslash_count = 0
                        j = i - 1
                        while j >= 0 and raw_value[j] == "\\":
                            backslash_count += 1
                            j -= 1

                        if ch == ":":
                            # 如果前面有偶數個反斜線，需要跳脫冒號
                            if backslash_count % 2 == 0:
                                result.append("\\:")
                            else:
                                result.append(":")
                            continue

                        # 跳脫等號（特別是前導的）
                        if i == 0 or backslash_count % 2 == 0:
                            result.append("\\=")
                        else:
                            result.append("=")
                        continue

                    if ch == " " and i == 0:
                        # 跳脫前導空格
                        result.append("\\ ")
                        continue
                    if ch == "\n":
                        result.append("\\n")
                        continue
                    if ch == "\r":
                        result.append("\\r")
                        continue
                    if ch == "\t":
                        result.append("\\t")
                        continue
                    if ch == "\f":
                        result.append("\\f")
                        continue

                    result.append(ch)

                return "".join(result)

            for key, value in properties.items():
                val_str = _escape_property_value(str(value))
                lines.append(f"{key}={val_str}")

            lines.append("")
            payload = "\n".join(lines)
            temp_path = properties_file.with_suffix(properties_file.suffix + ".tmp")
            if not PathUtils.write_text_file(temp_path, payload):
                raise OSError("write temp server.properties failed")
            PathUtils.move_path(temp_path, properties_file)
        except Exception as e:
            logger.exception(f"儲存 server.properties 失敗: {e}")


# ====== Server Properties 驗證器 ======
class ServerPropertiesValidator:
    """server.properties 屬性驗證器"""

    # 屬性驗證規則：屬性名稱 -> (類型, 最小值, 最大值, 允許的值)
    # Property validation rules: property_name -> (type, min_value, max_value, allowed_values)
    VALIDATION_RULES = {
        # 整數屬性
        "max-players": ("int", 0, 2147483647, None),
        "max-world-size": ("int", 1, 29999984, None),
        "server-port": ("int", 1, 65534, None),
        "query.port": ("int", 1, 65534, None),
        "rcon.port": ("int", 1, 65534, None),
        "entity-broadcast-range-percentage": ("int", 10, 1000, None),
        "function-permission-level": ("int", 1, 4, None),
        "op-permission-level": ("int", 0, 4, None),
        "max-tick-time": ("int", -1, None, None),  # -1 為停用
        "max-chained-neighbor-updates": ("int", None, None, None),
        "network-compression-threshold": ("int", -1, None, None),
        "simulation-distance": ("int", 3, 32, None),
        "view-distance": ("int", 3, 32, None),
        "spawn-protection": ("int", 0, None, None),
        "player-idle-timeout": ("int", 0, None, None),
        "pause-when-empty-seconds": ("int", -1, None, None),  # -1 為不停止
        "rate-limit": ("int", 0, None, None),
        "text-filtering-version": ("int", 0, None, None),
        "status-heartbeat-interval": ("int", 0, None, None),
        "management-server-port": ("int", 0, None, None),
        # 布林值屬性
        "accepts-transfers": ("bool", None, None, None),
        "allow-flight": ("bool", None, None, None),
        "allow-nether": ("bool", None, None, None),
        "broadcast-console-to-ops": ("bool", None, None, None),
        "broadcast-rcon-to-ops": ("bool", None, None, None),
        "enable-command-block": ("bool", None, None, None),
        "enable-jmx-monitoring": ("bool", None, None, None),
        "enable-query": ("bool", None, None, None),
        "enable-rcon": ("bool", None, None, None),
        "enable-status": ("bool", None, None, None),
        "enforce-secure-profile": ("bool", None, None, None),
        "enforce-whitelist": ("bool", None, None, None),
        "force-gamemode": ("bool", None, None, None),
        "generate-structures": ("bool", None, None, None),
        "hardcore": ("bool", None, None, None),
        "hide-online-players": ("bool", None, None, None),
        "log-ips": ("bool", None, None, None),
        "online-mode": ("bool", None, None, None),
        "prevent-proxy-connections": ("bool", None, None, None),
        "pvp": ("bool", None, None, None),
        "require-resource-pack": ("bool", None, None, None),
        "spawn-monsters": ("bool", None, None, None),
        "sync-chunk-writes": ("bool", None, None, None),
        "use-native-transport": ("bool", None, None, None),
        "white-list": ("bool", None, None, None),
        # 列舉屬性
        "gamemode": (
            "enum",
            None,
            None,
            ["survival", "creative", "adventure", "spectator", "0", "1", "2", "3"],
        ),
        "difficulty": (
            "enum",
            None,
            None,
            ["peaceful", "easy", "normal", "hard", "0", "1", "2", "3"],
        ),
        "level-type": (
            "enum",
            None,
            None,
            [
                "minecraft:normal",
                "minecraft:flat",
                "minecraft:large_biomes",
                "minecraft:amplified",
                "minecraft:single_biome_surface",
                "default",
                "flat",
                "large_biomes",
                "amplified",
                "buffet",
                "customized",
            ],
        ),
        "region-file-compression": ("enum", None, None, ["deflate", "none"]),
        # 字串屬性 - 無特定限制
        "bug-report-link": ("str", None, None, None),
        "generator-settings": ("str", None, None, None),
        "initial-disabled-packs": ("str", None, None, None),
        "initial-enabled-packs": ("str", None, None, None),
        "level-name": ("str", None, None, None),
        "level-seed": ("str", None, None, None),
        "motd": ("str", None, None, None),
        "rcon.password": ("str", None, None, None),
        "resource-pack": ("str", None, None, None),
        "resource-pack-id": ("str", None, None, None),
        "resource-pack-prompt": ("str", None, None, None),
        "resource-pack-sha1": ("str", None, None, None),
        "server-ip": ("str", None, None, None),
        "text-filtering-config": ("str", None, None, None),
    }

    @staticmethod
    def validate_property(prop_name: str, value: str) -> tuple[bool, str]:
        """驗證單一屬性"""
        if not prop_name or not value:
            return True, ""  # 允許空值

        rules = ServerPropertiesValidator.VALIDATION_RULES.get(prop_name)
        if not rules:
            # 未知屬性，但允許儲存
            return True, ""

        prop_type, min_val, max_val, allowed = rules

        try:
            if prop_type == "int":
                int_val = int(value)
                if min_val is not None and int_val < min_val:
                    return False, f"{prop_name}: 值不能小於 {min_val}（目前：{int_val}）"
                if max_val is not None and int_val > max_val:
                    return False, f"{prop_name}: 值不能大於 {max_val}（目前：{int_val}）"
                return True, ""

            if prop_type == "bool":
                if value.lower() not in ["true", "false"]:
                    return False, f"{prop_name}: 必須為 true 或 false（目前：{value}）"
                return True, ""

            if prop_type == "enum":
                if allowed is not None and value not in allowed:
                    return False, f"{prop_name}: 無效的值。允許值為：{', '.join(allowed)}（目前：{value}）"
                return True, ""

            if prop_type == "str":
                return True, ""

        except ValueError:
            return False, f"{prop_name}: 無效的 {prop_type} 值（目前：{value}）"

        return True, ""

    @staticmethod
    def validate_properties(properties: dict[str, str]) -> tuple[bool, list[str]]:
        """驗證多個屬性"""
        errors = []
        for prop_name, value in properties.items():
            is_valid, error_msg = ServerPropertiesValidator.validate_property(prop_name, value)
            if not is_valid:
                errors.append(error_msg)

        return len(errors) == 0, errors


# ====== 伺服器檢測工具類別 ======
class ServerDetectionUtils:
    """伺服器檢測工具類別，提供各種伺服器相關的檢測和驗證功能"""

    # ====== Shared Utility Methods ======
    @staticmethod
    def parse_mc_version(version_str: str) -> list[int]:
        """版本數字列表，如 [1, 20, 1]"""
        if not version_str or not isinstance(version_str, str):
            logger.debug(f"無效的 MC 版本字串: {version_str!r}")
            return []
        try:
            matches = re.findall(r"\d+", version_str)
            return [int(x) for x in matches] if matches else []
        except Exception as e:
            logger.exception(f"解析 MC 版本時發生錯誤: {e}")
            return []

    @staticmethod
    def is_fabric_compatible_version(mc_version: str) -> bool:
        """檢查 MC 版本是否與 Fabric 相容（1.14+）"""
        try:
            version_parts = ServerDetectionUtils.parse_mc_version(mc_version)
            if not version_parts:
                return False

            major = version_parts[0]
            minor = version_parts[1] if len(version_parts) > 1 else 0

            # Fabric supports 1.14+
            return bool(major > 1 or (major == 1 and minor >= 14))
        except Exception as e:
            logger.exception(f"檢查 Fabric 相容性時發生錯誤: {e}")
            return False

    @staticmethod
    def standardize_loader_type(loader_type: str, loader_version: str = "") -> str:
        """標準化載入器類型：將輸入轉為小寫並進行基本推斷"""
        lt_low = loader_type.lower()
        if lt_low not in ["unknown", "未知"]:
            return lt_low

        # fallback 推斷
        if loader_version and loader_version.replace(".", "").isdigit():
            return "forge"
        if loader_version and "fabric" in loader_version.lower():
            return "fabric"
        return "vanilla"

    @staticmethod
    def normalize_mc_version(mc_version) -> str:
        """標準化 Minecraft 版本字串"""
        if isinstance(mc_version, list) and mc_version:
            mc_version = str(mc_version[0])
        if isinstance(mc_version, str) and (mc_version.startswith(("[", "("))):
            m = re.search(r"(\d+\.\d+)", mc_version)
            if m:
                mc_version = m.group(1)
        return mc_version

    @staticmethod
    def clean_version(version: str) -> str:
        """清理後的版本字串"""
        if not version or version == "未知":
            return version
        # 移除後綴如 +、-mc、-fabric、-forge、-kotlin 等
        v = re.split(
            r"[+]|-mc|-fabric|-forge|-kotlin|-api|-universal|-common|-b[0-9]*|-beta|-alpha|-snapshot",
            version,
            flags=re.IGNORECASE,
        )[0]
        # 移除結尾的非英數字元
        v = re.sub(r"[^\w\d.]+$", "", v)
        return v.strip()

    @staticmethod
    def extract_mc_version_from_text(text: str) -> str | None:
        """從文本中提取 Minecraft 版本"""
        if not text:
            return None
        # 匹配常見的版本格式，按優先級排序
        patterns = [
            # Standard with minecraft prefix: minecraft:1.20.1 (最高優先級)
            (r"minecraft[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
            # Standard with mc prefix: mc:1.20.1
            (r"mc[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
            # Standard with version prefix: version:1.20.1
            (r"version[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
            # Pre-release/RC: 1.21.4-pre3, 1.21.4-rc1
            (r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?-(?:pre|rc)[0-9]+)\b", 2),
            # New snapshot format: 26.1-snapshot-5
            (r"\b([0-9]+\.[0-9]+-snapshot-[0-9]+)\b", 3),
            # Traditional snapshot: 24w14a, 25w46a
            (r"\b(2[0-9]w[0-9]{1,2}[a-z])\b", 3),
            # Standard version number: 1.20.1 (最低優先級，避免誤匹配)
            (r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b", 4),
        ]

        # 收集所有匹配結果及其優先級
        matches = []
        for pattern, priority in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                matches.append((m.group(1), priority))

        # 如果有多個匹配，返回優先級最高的（數字最小）
        if matches:
            matches.sort(key=lambda x: x[1])
            return matches[0][0]

        return None

    @staticmethod
    def detect_loader_from_text(text: str) -> str:
        """從文本中偵測載入器類型"""
        if not text:
            return "vanilla"
        text_lower = text.lower()
        if "fabric" in text_lower:
            return "fabric"
        if "forge" in text_lower:
            return "forge"
        return "vanilla"

    # ====== Loader Detection Methods (formerly LoaderDetector) ======
    @staticmethod
    def detect_loader_type(server_path: Path, jar_names: list[str]) -> str:
        """偵測載入器類型"""
        # Check for Fabric
        for fabric_jar in FABRIC_JAR_NAMES:
            if (server_path / fabric_jar).exists():
                return "fabric"

        # Check for Forge
        if (server_path / FORGE_LIBRARY_PATH).is_dir():
            return "forge"

        # Check JAR names
        jar_names_lower = [n.lower() for n in jar_names]
        for name in jar_names_lower:
            if "fabric" in name:
                return "fabric"
            if "forge" in name:
                return "forge"

        return "vanilla"

    @staticmethod
    def extract_version_from_forge_path(path_str: str) -> tuple[str | None, str | None]:
        """從 Forge 路徑字串提取版本資訊"""
        if not path_str:
            return None, None

        # 移除 .jar 後綴和 "forge-" 前綴
        clean_str = path_str
        if clean_str.endswith(".jar"):
            clean_str = clean_str[:-4]
        if clean_str.startswith("forge-"):
            clean_str = clean_str[6:]

        # 匹配多種 Forge 版本格式:
        # 1. 標準格式: "1.20.1-47.3.29" (MC版本-Forge版本)
        # 2. 舊版格式: "1.12.2-14.23.5.2859" (4段Forge版本號)
        # 3. 短版格式: "1.7.10-10.13" (2段Forge版本號)
        patterns = [
            # 匹配: MC版本(1-3段)-Forge版本(2-4段)
            r"^(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)$",
            # 匹配帶額外標記的: 1.20.1-47.3.29-installer
            r"^(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)-.*$",
        ]

        for pattern in patterns:
            match = re.match(pattern, clean_str)
            if match:
                mc_ver = match.group(1)
                forge_ver = match.group(2)
                # 驗證版本號格式合理
                if mc_ver and forge_ver and len(mc_ver.split(".")) >= 2 and len(forge_ver.split(".")) >= 2:
                    return mc_ver, forge_ver

        return None, None

    # ====== Server JAR Location Methods (formerly ServerJarLocator) ======
    @staticmethod
    def find_main_jar(server_path: Path, loader_type: str, server_config=None) -> str:
        """尋找主要 JAR 檔案，根據載入器類型和伺服器配置進行優先級檢測"""
        loader_type = (loader_type or "").lower()

        # Forge server
        if loader_type == "forge":
            # Check for win_args.txt (Forge 1.17+)
            args_file = ServerDetectionUtils.find_forge_args_file(server_path, server_config)
            if args_file and args_file.exists():
                # 返回相對於 server_path 的路徑（Java @ 參數需要相對路徑）
                try:
                    relative_path = args_file.relative_to(server_path)
                    return f"@{relative_path.as_posix()}"
                except ValueError:
                    # 如果無法獲取相對路徑，使用檔名
                    return f"@{args_file.name}"

            # Check for forge JAR files
            for jar_file in server_path.glob("*.jar"):
                if "forge" in jar_file.name.lower():
                    return jar_file.name

        # Fabric server
        elif loader_type == "fabric":
            for fabric_jar in FABRIC_JAR_NAMES:
                if (server_path / fabric_jar).exists():
                    return fabric_jar

        # Vanilla or fallback
        for jar_name in ["server.jar", "minecraft_server.jar"]:
            if (server_path / jar_name).exists():
                return jar_name

        # Fallback: any JAR file
        jar_files = list(server_path.glob("*.jar"))
        if jar_files:
            return jar_files[0].name

        return "server.jar"

    # ====== Original Methods ======
    @staticmethod
    def find_startup_script(server_path: Path) -> Path | None:
        """尋找伺服器啟動腳本"""
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
        """檢查伺服器資料夾中缺少的關鍵檔案清單"""
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
        """檢測 eula.txt 檔案中是否已設定 eula=true"""
        eula_file = server_path / "eula.txt"
        if not eula_file.exists():
            return False

        try:
            content = PathUtils.read_text_file(eula_file, errors="ignore") or ""

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
    def _process_startup_script(file_path: Path) -> tuple[str, bool, int | None, int | None]:
        """處理啟動腳本：移除 pause、添加 nogui、提取記憶體設定"""
        modified = False
        max_m = None
        min_m = None
        new_lines = []
        content = PathUtils.read_text_file(file_path, errors="ignore")
        if not content:
            return "", False, None, None

        for line in content.splitlines(keepends=True):
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

            new_lines.append(line)

        return "".join(new_lines), modified, max_m, min_m

    @staticmethod
    def _detect_memory_from_file(file_path: Path, is_script: bool = False) -> tuple[int | None, int | None]:
        """從單個檔案偵測記憶體設定（統一接口）"""
        if not file_path.exists():
            return None, None

        try:
            if is_script:
                # 處理啟動腳本（可能修改檔案）
                script_content, modified, max_m, min_m = ServerDetectionUtils._process_startup_script(file_path)

                # 如果修改了腳本，寫回檔案
                if modified:
                    try:
                        PathUtils.write_text_file(file_path, script_content)
                        logger.info(f"已優化啟動腳本: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"無法更新腳本 {file_path}: {e}")

                return max_m, min_m
            # 處理參數檔（只讀取）
            content = PathUtils.read_text_file(file_path, errors="ignore") or ""

            max_m = MemoryUtils.parse_memory_setting(content, "Xmx")
            min_m = MemoryUtils.parse_memory_setting(content, "Xms")
            return max_m, min_m

        except Exception as e:
            logger.debug(f"讀取記憶體檔案失敗 {file_path}: {e}")
            return None, None

    @staticmethod
    def update_forge_user_jvm_args(server_path: Path, config: ServerConfig) -> None:
        """更新新版 Forge 的 user_jvm_args.txt 檔案，設定記憶體參數"""
        user_jvm_args_path = server_path / "user_jvm_args.txt"
        lines = []
        if config.memory_min_mb:
            lines.append(f"-Xms{config.memory_min_mb}M\n")
        if config.memory_max_mb:
            lines.append(f"-Xmx{config.memory_max_mb}M\n")
        try:
            PathUtils.write_text_file(user_jvm_args_path, "".join(lines))
        except Exception as e:
            logger.exception(f"寫入失敗: {e}")
            UIUtils.show_error(
                "寫入失敗",
                f"無法更新 {user_jvm_args_path} 檔案。請檢查權限或磁碟空間。錯誤: {e}",
            )

    @staticmethod
    def detect_memory_from_sources(server_path: Path, config: ServerConfig) -> None:
        """檢測記憶體大小 - 簡化版本"""
        # 優先級順序掃描
        memory_sources = [
            [("user_jvm_args.txt", False), ("jvm.args", False)],
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
            # 若未設定最小記憶體則交由Java自行決定取用的記憶體量
            config.memory_min_mb = min_mem if min_mem is not None else None
        elif min_mem is not None:
            config.memory_max_mb = min_mem
            config.memory_min_mb = min_mem

        # Forge 特殊處理
        if hasattr(config, "loader_type") and str(getattr(config, "loader_type", "")).lower() == "forge":
            ServerDetectionUtils.update_forge_user_jvm_args(server_path, config)

    @staticmethod
    def detect_server_type(server_path: Path, config: "ServerConfig", print_result: bool = True) -> None:
        """檢測伺服器類型和版本 - 統一的偵測邏輯"""
        try:
            jar_files = list(server_path.glob("*.jar"))
            jar_names = [f.name for f in jar_files]

            detection_source = {}  # 紀錄偵測來源

            # 使用 ServerDetectionUtils 進行統一偵測
            detected_loader = ServerDetectionUtils.detect_loader_type(server_path, jar_names)
            config.loader_type = detected_loader

            # 記錄偵測來源（用於日誌）
            if detected_loader == "fabric":
                detected_file = next((f for f in FABRIC_JAR_NAMES if (server_path / f).exists()), None)
                detection_source["loader_type"] = f"檔案 {detected_file}" if detected_file else "Fabric 檔案"
            elif detected_loader == "forge":
                if (server_path / FORGE_LIBRARY_PATH).is_dir():
                    detection_source["loader_type"] = f"目錄 {FORGE_LIBRARY_PATH}"
                else:
                    detected_file = next((name for name in jar_names if "forge" in name.lower()), None)
                    detection_source["loader_type"] = f"JAR 檔案 {detected_file}" if detected_file else "Forge JAR"
            elif detected_loader == "vanilla":
                detected_file = next(
                    (name for name in jar_names if name.lower() in ("server.jar", "minecraft_server.jar")), None
                )
                detection_source["loader_type"] = f"JAR 檔案 {detected_file}" if detected_file else "Vanilla JAR"
            else:
                detection_source["loader_type"] = "無法判斷"

            ServerDetectionUtils.detect_loader_and_version_from_sources(
                server_path,
                config,
                config.loader_type,
                detection_source,
            )

            ServerDetectionUtils.detect_memory_from_sources(server_path, config)

            detected_main_jar = ServerDetectionUtils.find_main_jar(server_path, config.loader_type, config)
            config.eula_accepted = ServerDetectionUtils.detect_eula_acceptance(server_path)

            if print_result:
                logger.info(f"偵測結果 - 路徑: {server_path.name}")
                logger.info(f"  載入器: {config.loader_type} (來源: {detection_source.get('loader_type', '未知')})")
                if detection_source.get("mc_version"):
                    logger.info(f"  MC版本: {config.minecraft_version} (來源: {detection_source['mc_version']})")
                else:
                    logger.info(f"  MC版本: {config.minecraft_version}")
                if detection_source.get("loader_version"):
                    logger.info(f"  載入器版本: {config.loader_version} (來源: {detection_source['loader_version']})")
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
        """檢查是否為有效的 Minecraft 伺服器資料夾"""
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
        """取得最新的日誌檔，優先級: 時間戳 > 標準名稱"""
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
        """從多種來源偵測 Fabric/Forge 載入器與 Minecraft 版"""
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
            """從日誌檔偵測載入器和 Minecraft 版本 - 改進版本"""
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
                content = PathUtils.read_text_file(log_file, errors="ignore")
                if content:
                    lines = content.splitlines(keepends=True)[:2000]
                    content = "".join(lines)
                else:
                    return
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
            mc, forge_ver = ServerDetectionUtils.extract_version_from_forge_path(folder)
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
            data = PathUtils.load_json(fp)
            if not data:
                return
            if "id" in data:
                set_if_unknown("minecraft_version", data["id"])
            if "forgeVersion" in data:
                set_if_unknown("loader_version", data["forgeVersion"])

        detect_from_logs()

        if loader == "fabric" and is_unknown(config.loader_version):
            config.loader_version = "unknown"

        if loader == "forge":
            detect_from_forge_lib()

        detect_from_jars()
        detect_from_version_json()

        if is_unknown(config.loader_type) and is_unknown(config.loader_version):
            config.loader_type = "vanilla"

    @staticmethod
    def find_forge_args_file(server_path: Path, server_config=None) -> Path | None:
        """尋找 Forge 的 win_args.txt 啟動參數檔"""
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
        """包含以下可能的鍵值對："""
        result: dict[str, str | list[str] | None] = {
            "jar": None,
            "bootstraplauncher": None,
            "forge_libraries": [],
            "minecraft_version": None,
            "forge_version": None,
        }

        try:
            content = PathUtils.read_text_file(args_path, errors="ignore") or ""

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
            mc_ver, forge_ver = ServerDetectionUtils.extract_version_from_forge_path(parent_dir)
            if mc_ver and forge_ver:
                result["minecraft_version"] = mc_ver
                result["forge_version"] = forge_ver
                logger.info(f"從 Forge 目錄路徑提取版本: MC={mc_ver}, Forge={forge_ver}")

        except Exception as e:
            logger.warning(f"解析 win_args.txt 失敗: {e}")

        return result


# ====== 伺服器操作工具類別 Server Operations ======
class ServerOperations:
    """伺服器操作工具類別"""

    @staticmethod
    def get_status_text(is_running: bool) -> tuple:
        """獲取狀態文字和顏色"""
        return ("🟢 狀態: 運行中", "green") if is_running else ("🔴 狀態: 已停止", "red")

    @staticmethod
    def graceful_stop_server(server_manager, server_name: str) -> bool:
        """優雅停止伺服器（先嘗試 stop 命令，失敗則強制停止）"""
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
    """伺服器指令工具類別"""

    @staticmethod
    def build_java_command(server_config, return_list=False) -> list | str:
        """構建 Java 啟動命令，根據伺服器配置自動偵測主要 JAR 和載入器類型"""
        server_path = Path(server_config.path)
        loader_type = str(server_config.loader_type or "").lower()
        memory_min = server_config.memory_min_mb if server_config.memory_min_mb else None
        memory_max = server_config.memory_max_mb if server_config.memory_max_mb else 2048

        # 確保 JVM 記憶體參數有效：當設定了最小記憶體時，最大記憶體至少要大於等於最小值
        if memory_min is not None and (memory_max is None or memory_max < memory_min):
            memory_max = memory_min

        java_exe = JavaUtils.get_best_java_path(str(getattr(server_config, "minecraft_version", ""))) or "java"
        java_exe = java_exe.replace("javaw.exe", "java.exe")

        # 偵測主要 JAR/參數檔
        main_jar = ServerDetectionUtils.find_main_jar(server_path, loader_type, server_config)

        # ============ 根據 loader_type 構建命令 ============

        # Forge 伺服器：檢查啟動參數檔格式
        if loader_type == "forge" and main_jar.startswith("@"):
            # 使用參數檔啟動 (1.20.1 類型或需要參數檔的版本)
            cmd_list = [java_exe, main_jar, "nogui"]
            result_cmd = f"{java_exe} {main_jar} nogui"

        # Vanilla 或 Fabric 伺服器 / 或 Forge Modern 版本
        else:
            # 構建命令列表
            cmd_list = [java_exe]
            if memory_min:
                cmd_list.append(f"-Xms{memory_min}M")
            cmd_list.extend(
                [
                    f"-Xmx{memory_max}M",
                    "-jar",
                    main_jar,
                    "nogui",
                ]
            )

            # 構建字符串版本，處理路徑中有空格的情況
            if " " in java_exe and not (java_exe.startswith('"') and java_exe.endswith('"')):
                java_exe_quoted = f'"{java_exe}"'
            else:
                java_exe_quoted = java_exe

            if " " in main_jar and not (main_jar.startswith('"') and main_jar.endswith('"')):
                main_jar_quoted = f'"{main_jar}"'
            else:
                main_jar_quoted = main_jar

            memory_args = f"-Xms{memory_min}M -Xmx{memory_max}M" if memory_min else f"-Xmx{memory_max}M"
            result_cmd = f"{java_exe_quoted} {memory_args} -jar {main_jar_quoted} nogui"

        if return_list:
            return cmd_list
        return result_cmd
