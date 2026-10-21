namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器通用預設值與標準檔案名稱常數定義
/// </summary>
public static class ServerDefaults
{
    /// <summary>
    /// 伺服器預設最大記憶體配置 (MB)
    /// </summary>
    public const int DefaultMemoryMaxMb = 2048;

    /// <summary>
    /// 伺服器預設最小記憶體配置 (MB)
    /// </summary>
    public const int DefaultMemoryMinMb = 1024;

    /// <summary>
    /// Minecraft 伺服器標準預設通訊埠
    /// </summary>
    public const int DefaultPort = 25565;

    /// <summary>
    /// 標準伺服器屬性檔名
    /// </summary>
    public const string ServerPropertiesFileName = "server.properties";

    /// <summary>
    /// 終端使用者授權協議檔名
    /// </summary>
    public const string EulaFileName = "eula.txt";

    /// <summary>
    /// 管理員名單檔名
    /// </summary>
    public const string OpsFileName = "ops.json";

    /// <summary>
    /// 白名單檔名
    /// </summary>
    public const string WhitelistFileName = "whitelist.json";

    /// <summary>
    /// 玩家封鎖名單檔名
    /// </summary>
    public const string BannedPlayersFileName = "banned-players.json";

    /// <summary>
    /// IP 封鎖名單檔名
    /// </summary>
    public const string BannedIpsFileName = "banned-ips.json";

    /// <summary>
    /// 玩家快取索引檔名
    /// </summary>
    public const string UserCacheFileName = "usercache.json";

    /// <summary>
    /// Forge / NeoForge JVM 自訂參數檔名
    /// </summary>
    public const string UserJvmArgsFileName = "user_jvm_args.txt";

    /// <summary>
    /// Windows 標準啟動批次檔名
    /// </summary>
    public const string StartServerBatFileName = "start_server.bat";

    /// <summary>
    /// 載入器標準執行檔名 (run.bat)
    /// </summary>
    public const string RunBatFileName = "run.bat";

    /// <summary>
    /// 載入器標準執行檔名 (run.sh)
    /// </summary>
    public const string RunShFileName = "run.sh";
}
