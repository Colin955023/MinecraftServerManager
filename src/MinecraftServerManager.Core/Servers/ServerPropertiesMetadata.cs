using System.Collections.Frozen;

namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// Minecraft server.properties 屬性說明、分類與預設值中繼資料
/// </summary>
public static class ServerPropertiesMetadata
{
    private static readonly FrozenDictionary<string, string> DescriptionsMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["accepts-transfers"] = "是否允許伺服器端接受以 Transfer 封包作為登入請求的傳入連線 (false/true)",
        ["allow-flight"] = "是否允許玩家在生存模式下飛行 (false/true) 若設為 true，安裝了飛行模組的玩家可以飛行",
        ["allow-nether"] = "是否允許玩家進入地獄 (下界) (true/false) false - 玩家將無法通過地獄傳送門",
        ["broadcast-console-to-ops"] = "是否向所有線上 OP 送出所執行指令的輸出 (true/false)",
        ["broadcast-rcon-to-ops"] = "是否向所有線上 OP 送出通過 RCON 執行的指令的輸出 (true/false)",
        ["bug-report-link"] = "伺服器回報錯誤的 URL 顯示於中斷連線畫面",
        ["difficulty"] = "定義伺服器的遊戲難度 (peaceful/easy/normal/hard)",
        ["enable-code-of-conduct"] = "是否啟用行為準則顯示 (false/true)",
        ["enable-command-block"] = "是否啟用指令方塊 (false/true)",
        ["enable-jmx-monitoring"] = "是否啟用 JMX 監控 (false/true)",
        ["enable-query"] = "是否允許使用 GameSpy4 協定的伺服器監聽器 (false/true)",
        ["enable-rcon"] = "是否允許遠端存取伺服器控制台 (false/true)",
        ["enable-status"] = "使伺服器在伺服器列表中顯示為線上 (true/false)",
        ["enforce-secure-profile"] = "要求玩家必須具有 Mojang 簽名的公鑰才能進入伺服器 (true/false)",
        ["enforce-whitelist"] = "在伺服器上強制執行白名單 (false/true)",
        ["entity-broadcast-range-percentage"] = "實體廣播範圍百分比 (10-1000)",
        ["force-gamemode"] = "是否強制玩家加入時為預設遊戲模式 (false/true)",
        ["function-permission-level"] = "設定函式解析時的權限等級 (1-4)",
        ["gamemode"] = "定義新玩家的預設遊戲模式 (survival/creative/adventure/spectator)",
        ["generate-structures"] = "定義是否生成結構 (如村莊) (true/false)",
        ["generator-settings"] = "自訂世界的生成設定 (JSON 格式)",
        ["hardcore"] = "是否啟用極限模式 (false/true)",
        ["hide-online-players"] = "是否在伺服器列表中隱藏線上玩家清單 (false/true)",
        ["initial-disabled-packs"] = "建立世界時要停用的資料包名稱 (逗號分隔)",
        ["initial-enabled-packs"] = "建立世界時要啟用的資料包名稱 (逗號分隔)",
        ["level-name"] = "世界名稱及其資料夾名稱 (預設: world)",
        ["level-seed"] = "世界種子碼，留空則隨機生成",
        ["level-type"] = "世界生成類型 ID (例如: minecraft:normal, minecraft:flat 等)",
        ["log-ips"] = "是否在伺服器日誌中記錄玩家 IP (true/false)",
        ["max-chained-neighbor-updates"] = "限制連鎖方塊更新的數量 (負數為無限制)",
        ["max-players"] = "伺服器最大玩家數量 (0-2147483647)",
        ["max-tick-time"] = "每個 tick 花費的最大毫秒數 (-1 可停用監視逾時)",
        ["max-world-size"] = "世界邊界的最大半徑 (1-29999984)",
        ["motd"] = "伺服器列表顯示的訊息，支援樣式代碼",
        ["network-compression-threshold"] = "網路壓縮閾值 (-1 為停用壓縮)",
        ["online-mode"] = "是否啟用線上驗證 (正版驗證) (true/false)",
        ["op-permission-level"] = "OP 管理員的預設權限等級 (0-4)",
        ["pause-when-empty-seconds"] = "伺服器無人時自動停止計算的等待秒數 (負數為不停止)",
        ["player-idle-timeout"] = "玩家閒置踢出時間 (分鐘) (0 為不踢出)",
        ["prevent-proxy-connections"] = "是否阻止代理或 VPN 連線 (false/true)",
        ["pvp"] = "是否啟用玩家對戰 (PVP) (true/false)",
        ["query.port"] = "GameSpy4 查詢監聽連接埠 (1-65534)",
        ["rate-limit"] = "玩家送出封包的速率限制 (0 為無限制)",
        ["rcon.password"] = "RCON 遠端存取的密碼",
        ["rcon.port"] = "RCON 遠端存取的連接埠 (1-65534)",
        ["region-file-compression"] = "區域檔案壓縮演算法 (deflate/lz4/none)",
        ["require-resource-pack"] = "是否強制玩家使用伺服器資源包 (false/true)",
        ["resource-pack"] = "資源包下載 URL (直連)",
        ["resource-pack-id"] = "資源包的 UUID",
        ["resource-pack-prompt"] = "自訂資源包提示訊息",
        ["resource-pack-sha1"] = "資源包的 SHA-1 雜湊值",
        ["server-ip"] = "伺服器綁定 IP (建議留空綁定全部介面)",
        ["server-port"] = "伺服器監聽連接埠 (1-65534, 預設: 25565)",
        ["simulation-distance"] = "模擬距離區塊半徑 (3-32)",
        ["spawn-monsters"] = "是否生成怪物 (true/false)",
        ["spawn-protection"] = "重生點保護半徑 (0 為停用)",
        ["text-filtering-config"] = "文字過濾設定檔路徑",
        ["use-native-transport"] = "是否使用 Linux 專用網路最佳化 (true/false)",
        ["view-distance"] = "伺服器視距區塊半徑 (3-32)",
        ["white-list"] = "是否啟用白名單 (false/true)",
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string> DefaultsMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["accepts-transfers"] = "false",
        ["allow-flight"] = "false",
        ["allow-nether"] = "true",
        ["broadcast-console-to-ops"] = "true",
        ["broadcast-rcon-to-ops"] = "true",
        ["difficulty"] = "easy",
        ["enable-command-block"] = "false",
        ["enable-jmx-monitoring"] = "false",
        ["enable-query"] = "false",
        ["enable-rcon"] = "false",
        ["enable-status"] = "true",
        ["enforce-secure-profile"] = "true",
        ["enforce-whitelist"] = "false",
        ["entity-broadcast-range-percentage"] = "100",
        ["force-gamemode"] = "false",
        ["function-permission-level"] = "2",
        ["gamemode"] = "survival",
        ["generate-structures"] = "true",
        ["hardcore"] = "false",
        ["hide-online-players"] = "false",
        ["level-name"] = "world",
        ["level-type"] = "minecraft:normal",
        ["log-ips"] = "true",
        ["max-players"] = "20",
        ["max-tick-time"] = "60000",
        ["max-world-size"] = "29999984",
        ["motd"] = "A Minecraft Server",
        ["network-compression-threshold"] = "256",
        ["online-mode"] = "true",
        ["op-permission-level"] = "4",
        ["pause-when-empty-seconds"] = "60",
        ["player-idle-timeout"] = "0",
        ["prevent-proxy-connections"] = "false",
        ["pvp"] = "true",
        ["query.port"] = "25565",
        ["rate-limit"] = "0",
        ["rcon.port"] = "25575",
        ["region-file-compression"] = "deflate",
        ["require-resource-pack"] = "false",
        ["server-port"] = "25565",
        ["simulation-distance"] = "10",
        ["spawn-monsters"] = "true",
        ["spawn-protection"] = "16",
        ["use-native-transport"] = "true",
        ["view-distance"] = "10",
        ["white-list"] = "false",
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string> CategoriesDict = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["motd"] = "基本設定",
        ["server-port"] = "基本設定",
        ["server-ip"] = "基本設定",
        ["max-players"] = "基本設定",
        ["online-mode"] = "基本設定",
        ["white-list"] = "基本設定",
        ["enforce-whitelist"] = "基本設定",
        ["enable-status"] = "基本設定",
        ["hide-online-players"] = "基本設定",
        ["bug-report-link"] = "基本設定",

        ["difficulty"] = "遊戲設定",
        ["gamemode"] = "遊戲設定",
        ["force-gamemode"] = "遊戲設定",
        ["hardcore"] = "遊戲設定",
        ["pvp"] = "遊戲設定",
        ["spawn-monsters"] = "遊戲設定",
        ["allow-nether"] = "遊戲設定",
        ["allow-flight"] = "遊戲設定",
        ["spawn-protection"] = "遊戲設定",
        ["player-idle-timeout"] = "遊戲設定",
        ["enable-command-block"] = "遊戲設定",
        ["op-permission-level"] = "遊戲設定",
        ["function-permission-level"] = "遊戲設定",
        ["broadcast-console-to-ops"] = "遊戲設定",
        ["broadcast-rcon-to-ops"] = "遊戲設定",

        ["level-name"] = "世界設定",
        ["level-seed"] = "世界設定",
        ["level-type"] = "世界設定",
        ["generate-structures"] = "世界設定",
        ["generator-settings"] = "世界設定",
        ["view-distance"] = "世界設定",
        ["simulation-distance"] = "世界設定",
        ["max-world-size"] = "世界設定",
        ["initial-enabled-packs"] = "世界設定",
        ["initial-disabled-packs"] = "世界設定",

        ["enforce-secure-profile"] = "網路與安全",
        ["prevent-proxy-connections"] = "網路與安全",
        ["log-ips"] = "網路與安全",
        ["rate-limit"] = "網路與安全",
        ["network-compression-threshold"] = "網路與安全",
        ["use-native-transport"] = "網路與安全",
        ["accepts-transfers"] = "網路與安全",
        ["text-filtering-config"] = "網路與安全",
        ["region-file-compression"] = "網路與安全",

        ["enable-query"] = "遠端與進階",
        ["query.port"] = "遠端與進階",
        ["enable-rcon"] = "遠端與進階",
        ["rcon.port"] = "遠端與進階",
        ["rcon.password"] = "遠端與進階",
        ["enable-jmx-monitoring"] = "遠端與進階",
        ["max-tick-time"] = "遠端與進階",
        ["pause-when-empty-seconds"] = "遠端與進階",
        ["entity-broadcast-range-percentage"] = "遠端與進階",
        ["max-chained-neighbor-updates"] = "遠端與進階",
        ["enable-code-of-conduct"] = "遠端與進階",
        ["require-resource-pack"] = "遠端與進階",
        ["resource-pack"] = "遠端與進階",
        ["resource-pack-id"] = "遠端與進階",
        ["resource-pack-sha1"] = "遠端與進階",
        ["resource-pack-prompt"] = "遠端與進階",
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string[]> OptionsDict = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
    {
        ["difficulty"] = ["peaceful", "easy", "normal", "hard"],
        ["gamemode"] = ["survival", "creative", "adventure", "spectator"],
        ["region-file-compression"] = ["deflate", "lz4", "none"],
        ["level-type"] = ["minecraft:normal", "minecraft:flat", "minecraft:large_biomes", "minecraft:amplified"],
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    public static readonly IReadOnlyDictionary<string, string> Descriptions = DescriptionsMap;
    public static readonly IReadOnlyDictionary<string, string> DefaultProperties = DefaultsMap;
    public static readonly IReadOnlyDictionary<string, string> Categories = CategoriesDict;
    public static readonly IReadOnlyDictionary<string, string[]> Options = OptionsDict;

    public static readonly FrozenSet<string> BooleanKeys = new[]
    {
        "accepts-transfers",
        "allow-flight",
        "allow-nether",
        "broadcast-console-to-ops",
        "broadcast-rcon-to-ops",
        "enable-code-of-conduct",
        "enable-command-block",
        "enable-jmx-monitoring",
        "enable-query",
        "enable-rcon",
        "enable-status",
        "enforce-secure-profile",
        "enforce-whitelist",
        "force-gamemode",
        "generate-structures",
        "hardcore",
        "hide-online-players",
        "log-ips",
        "online-mode",
        "prevent-proxy-connections",
        "pvp",
        "require-resource-pack",
        "spawn-monsters",
        "use-native-transport",
        "white-list",
    }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    public static string GetDescription(string key) =>
        DescriptionsMap.TryGetValue(key, out string? desc) ? desc : $"自訂或未知的伺服器屬性：{key}";

    public static string GetDefault(string key, string fallback = "") =>
        DefaultsMap.TryGetValue(key, out string? def) ? def : fallback;

    public static string GetCategory(string key) =>
        CategoriesDict.TryGetValue(key, out string? cat) ? cat : "自訂屬性";

    public static string[]? GetOptions(string key) =>
        OptionsDict.TryGetValue(key, out string[]? opts) ? opts : null;
}
