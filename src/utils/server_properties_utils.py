"""伺服器屬性工具模組
提供 server.properties 載入/儲存與驗證相關工具。
"""

import re
import types
from pathlib import Path

from . import PathUtils, get_logger

logger = get_logger().bind(component="ServerPropertiesUtils")

__all__ = ["ServerPropertiesHelper", "ServerPropertiesValidator"]


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
            "bug-report-link": "伺服器「報告伺服器錯誤」的URL。 (字串) 顯示於玩家中斷連線畫面，引導玩家回報錯誤。",
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
