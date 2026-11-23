using System.Collections.Frozen;
using System.Collections.Immutable;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Servers;

/// <summary>單一 server.properties 屬性之分類、預設值、說明與選項</summary>
public sealed record PropertyMeta(
    string Category,
    string DefaultValue,
    string Description,
    bool IsBoolean = false,
    ImmutableArray<string> Options = default);

/// <summary>server.properties 屬性說明、分類與預設值</summary>
public static class ServerPropertiesMetadata
{
    private const string CustomCategory = "自訂屬性";

    private static readonly FrozenDictionary<string, PropertyMeta> Properties = new Dictionary<string, PropertyMeta>(StringComparer.OrdinalIgnoreCase)
    {
        ["accepts-transfers"] = new("網路與安全", "false", "是否允許伺服器端接受以 Transfer 封包作為登入請求的傳入連線 (false/true)", IsBoolean: true),
        ["allow-flight"] = new("遊戲設定", "false", "是否允許玩家在生存模式下飛行 (false/true) 若設為 true，安裝了飛行模組的玩家可以飛行", IsBoolean: true),
        ["allow-nether"] = new("遊戲設定", "true", "是否允許玩家進入地獄 (下界) (true/false) false - 玩家將無法通過地獄傳送門", IsBoolean: true),
        ["allowed-connection-ids"] = new("網路與安全", string.Empty, "限制連線至伺服器所需的連線 ID 清單 (以逗號分隔，留空則不限制)"),
        ["broadcast-console-to-ops"] = new("遊戲設定", "true", "是否向所有線上 OP 送出所執行指令的輸出 (true/false)", IsBoolean: true),
        ["broadcast-rcon-to-ops"] = new("遊戲設定", "true", "是否向所有線上 OP 送出透過 RCON 執行的指令的輸出 (true/false)", IsBoolean: true),
        ["bug-report-link"] = new("基本設定", string.Empty, "伺服器回報錯誤的 URL 顯示於中斷連線畫面"),
        ["chat-spam-threshold-seconds"] = new("遊戲設定", "10", "伺服器踢出聊天訊息傳送過於頻繁之玩家的時間門檻值 (秒，0 為不限制)"),
        ["command-spam-threshold-seconds"] = new("遊戲設定", "10", "伺服器踢出指令傳送過於頻繁之玩家的時間門檻值 (秒，0 為不限制)"),
        ["debug"] = new("遠端與進階", "false", "是否啟用伺服器除錯模式 (false/true) [Paper 專有]", IsBoolean: true),
        ["difficulty"] = new("遊戲設定", "easy", "定義伺服器的遊戲難度 (peaceful/easy/normal/hard)", Options: ["peaceful", "easy", "normal", "hard"]),
        ["enable-code-of-conduct"] = new("遠端與進階", "false", "是否啟用行為準則顯示 (false/true)", IsBoolean: true),
        ["enable-command-block"] = new("遊戲設定", "false", "是否啟用指令方塊 (false/true)", IsBoolean: true),
        ["enable-jmx-monitoring"] = new("遠端與進階", "false", "是否啟用 JMX 監控 (false/true)", IsBoolean: true),
        ["enable-legacy-status"] = new("基本設定", "true", "是否啟用 1.7 之前的舊版伺服器狀態與 ping 回應協定 (true/false)", IsBoolean: true),
        ["enable-query"] = new("遠端與進階", "false", "是否允許使用 GameSpy4 協定的伺服器監聽器 (false/true)", IsBoolean: true),
        ["enable-rcon"] = new("遠端與進階", "false", "是否允許遠端存取伺服器主控台 (false/true)", IsBoolean: true),
        ["enable-status"] = new("基本設定", "true", "使伺服器在伺服器清單中顯示為線上 (true/false)", IsBoolean: true),
        ["enforce-secure-profile"] = new("網路與安全", "true", "要求玩家必須具有 Mojang 簽章的公開金鑰才能進入伺服器 (true/false)", IsBoolean: true),
        ["enforce-whitelist"] = new("基本設定", "false", "在伺服器上強制執行白名單 (false/true)", IsBoolean: true),
        ["entity-broadcast-range-percentage"] = new("遠端與進階", "100", "實體廣播範圍百分比 (10-1000)"),
        ["force-gamemode"] = new("遊戲設定", "false", "是否強制玩家加入時為預設遊戲模式 (false/true)", IsBoolean: true),
        ["function-permission-level"] = new("遊戲設定", "2", "設定函式解析時的權限等級 (0-4)"),
        ["gamemode"] = new("遊戲設定", "survival", "定義新玩家的預設遊戲模式 (survival/creative/adventure/spectator)", Options: ["survival", "creative", "adventure", "spectator"]),
        ["generate-structures"] = new("世界設定", "true", "定義是否生成結構 (如村莊) (true/false)", IsBoolean: true),
        ["generator-settings"] = new("世界設定", "{}", "自訂世界的生成設定 (JSON 格式)"),
        ["hardcore"] = new("遊戲設定", "false", "是否啟用極限模式 (false/true)", IsBoolean: true),
        ["hide-online-players"] = new("基本設定", "false", "是否在伺服器清單中隱藏線上玩家清單 (false/true)", IsBoolean: true),
        ["initial-disabled-packs"] = new("世界設定", string.Empty, "建立世界時要停用的資料包名稱 (逗號分隔)"),
        ["initial-enabled-packs"] = new("世界設定", "vanilla", "建立世界時要啟用的資料包名稱 (逗號分隔)"),
        ["level-name"] = new("世界設定", "world", "世界名稱及其資料夾名稱 (預設: world)"),
        ["level-seed"] = new("世界設定", string.Empty, "世界種子碼，留空則隨機生成"),
        ["level-type"] = new("世界設定", "minecraft:normal", "世界生成類型 ID (例如: minecraft:normal, minecraft:flat 等)", Options: ["minecraft:normal", "minecraft:flat", "minecraft:large_biomes", "minecraft:amplified"]),
        ["log-ips"] = new("網路與安全", "true", "是否在伺服器記錄檔中記錄玩家 IP (true/false)", IsBoolean: true),
        ["management-server-allowed-origins"] = new("遠端與進階", string.Empty, "管理端伺服器允許的跨來源請求 (CORS Origins，逗號分隔)"),
        ["management-server-enabled"] = new("遠端與進階", "false", "是否啟用 Minecraft 伺服器管理協定 (管理端伺服器) (false/true)", IsBoolean: true),
        ["management-server-host"] = new("遠端與進階", "localhost", "管理端協定接聽的主機位址 (預設: localhost)"),
        ["management-server-port"] = new("遠端與進階", "0", "管理端協定接聽的連接埠 (0 為隨機指派)"),
        ["management-server-secret"] = new("遠端與進階", string.Empty, "管理端連線 Authorization 認證金鑰 (40 字元英數字)"),
        ["management-server-tls-enabled"] = new("遠端與進階", "true", "管理端協定是否啟用 TLS 加密傳輸 (true/false)", IsBoolean: true),
        ["management-server-tls-keystore"] = new("遠端與進階", string.Empty, "管理端 TLS 憑證庫檔案路徑 (keystore)"),
        ["management-server-tls-keystore-password"] = new("遠端與進階", string.Empty, "管理端 TLS 憑證庫存取密碼"),
        ["max-chained-neighbor-updates"] = new("遠端與進階", "1000000", "限制連鎖方塊更新的數量 (負數為無限制)"),
        ["max-players"] = new("基本設定", "20", "伺服器最大玩家數量 (0-2147483647)"),
        ["max-tick-time"] = new("遠端與進階", "60000", "每個 tick 花費的最大毫秒數 (-1 可停用監視逾時)"),
        ["max-world-size"] = new("世界設定", "29999984", "世界邊界的最大半徑 (1-29999984)"),
        ["motd"] = new("基本設定", "A Minecraft Server", "伺服器清單顯示的訊息，支援樣式代碼"),
        ["network-compression-threshold"] = new("網路與安全", "256", "網路壓縮門檻值 (-1 為停用壓縮)"),
        ["online-mode"] = new("基本設定", "true", "是否啟用線上驗證 (正版驗證) (true/false)", IsBoolean: true),
        ["op-permission-level"] = new("遊戲設定", "4", "OP 管理員的預設權限等級 (0-4)"),
        ["pause-when-empty-seconds"] = new("遠端與進階", "60", "伺服器無人時自動停止計算的等待秒數 (負數為不停止)"),
        ["player-idle-timeout"] = new("遊戲設定", "0", "玩家閒置踢出時間 (分鐘) (0 為不踢出)"),
        ["prevent-proxy-connections"] = new("網路與安全", "false", "是否阻止代理或 VPN 連線 (false/true)", IsBoolean: true),
        ["pvp"] = new("遊戲設定", "true", "是否啟用玩家對戰 (PVP) (true/false)", IsBoolean: true),
        ["query.port"] = new("遠端與進階", ServerDefaults.DefaultPort, "GameSpy4 查詢監聽連接埠 (1-65534)"),
        ["rate-limit"] = new("網路與安全", "0", "玩家送出封包的速率限制 (0 為無限制)"),
        ["rcon.password"] = new("遠端與進階", string.Empty, "RCON 遠端存取的密碼"),
        ["rcon.port"] = new("遠端與進階", "25575", "RCON 遠端存取的連接埠 (1-65534)"),
        ["region-file-compression"] = new("網路與安全", "deflate", "區域檔案壓縮演算法 (deflate/lz4/none)", Options: ["deflate", "lz4", "none"]),
        ["require-resource-pack"] = new("遠端與進階", "false", "是否強制玩家使用伺服器資源包 (false/true)", IsBoolean: true),
        ["resource-pack"] = new("遠端與進階", string.Empty, "資源包下載 URL (直連)"),
        ["resource-pack-id"] = new("遠端與進階", string.Empty, "資源包的 UUID"),
        ["resource-pack-prompt"] = new("遠端與進階", string.Empty, "自訂資源包提示訊息"),
        ["resource-pack-sha1"] = new("遠端與進階", string.Empty, "資源包的 SHA-1 雜湊值"),
        ["server-ip"] = new("基本設定", string.Empty, "伺服器繫結 IP (建議留空繫結全部介面)"),
        ["server-port"] = new("基本設定", ServerDefaults.DefaultPort, "伺服器監聽連接埠 (1-65534, 預設: 25565)"),
        ["simulation-distance"] = new("世界設定", "10", "模擬距離區塊半徑 (2-32)"),
        ["spawn-monsters"] = new("遊戲設定", "true", "是否生成怪物 (true/false)", IsBoolean: true),
        ["spawn-protection"] = new("遊戲設定", "16", "重生點保護半徑 (0 為停用)"),
        ["status-heartbeat-interval"] = new("遠端與進階", "0", "管理端伺服器向連線用戶端傳送心跳通知的間隔 (秒，0 為停用)"),
        ["sync-chunk-writes"] = new("世界設定", "true", "是否啟用同步寫入區塊資料 (true/false)", IsBoolean: true),
        ["text-filtering-config"] = new("網路與安全", string.Empty, "文字過濾設定檔路徑"),
        ["text-filtering-version"] = new("網路與安全", "0", "文字過濾設定格式版本 (0 或 1)"),
        ["use-native-transport"] = new("網路與安全", "true", "是否使用 Linux 專用網路最佳化 (true/false)", IsBoolean: true),
        ["view-distance"] = new("世界設定", "10", "伺服器視距區塊半徑 (2-32)"),
        ["white-list"] = new("基本設定", "false", "是否啟用白名單 (false/true)", IsBoolean: true),
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    /// <summary>所有已知屬性鍵</summary>
    public static ImmutableArray<string> KnownKeys => Properties.Keys;

    /// <summary>新建伺服器使用之預設屬性值</summary>
    public static readonly IReadOnlyDictionary<string, string> DefaultProperties =
        Properties.ToFrozenDictionary(static p => p.Key, static p => p.Value.DefaultValue, StringComparer.OrdinalIgnoreCase);

    /// <summary>屬性是否為布林值</summary>
    public static bool IsBoolean(string key) => Properties.TryGetValue(key, out var meta) && meta.IsBoolean;

    public static string GetDescription(string key) =>
        Properties.TryGetValue(key, out var meta) ? meta.Description : $"自訂或未知的伺服器屬性：{key}";

    public static string GetDefault(string key, string fallback = "") =>
        Properties.TryGetValue(key, out var meta) ? meta.DefaultValue : fallback;

    public static string GetCategory(string key) =>
        Properties.TryGetValue(key, out var meta) ? meta.Category : CustomCategory;

    /// <summary>取得列舉選項；非列舉屬性回傳 null</summary>
    public static IReadOnlyList<string>? GetOptions(string key) =>
        Properties.TryGetValue(key, out var meta) && !meta.Options.IsDefaultOrEmpty ? meta.Options : null;
}
