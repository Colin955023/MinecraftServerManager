namespace MinecraftServerManager.Domain.Servers;

/// <summary>伺服器通用預設值與標準檔案名稱常數定義</summary>
public static class ServerDefaults
{
    /// <summary>伺服器目錄下存放模組的子資料夾名稱</summary>
    public const string ModsDirectoryName = "mods";

    /// <summary>伺服器預設最大記憶體配置 (MB)</summary>
    public const int DefaultMemoryMaxMb = 2048;

    /// <summary>伺服器預設最小記憶體配置 (MB)</summary>
    public const int DefaultMemoryMinMb = 1024;

    /// <summary>每台伺服器預設保留的備份份數</summary>
    public const int DefaultBackupRetentionCount = 10;

    /// <summary>備份保留份數下限</summary>
    public const int MinBackupRetentionCount = 1;

    /// <summary>備份保留份數上限</summary>
    public const int MaxBackupRetentionCount = 100;

    /// <summary>平順停止伺服器之等待時間；逾時後由使用者決定繼續等待或強制終止</summary>
    public static readonly TimeSpan GracefulStopTimeout = TimeSpan.FromSeconds(60);

    /// <summary>Minecraft 伺服器標準預設通訊埠</summary>
    public const string DefaultPort = "25565";

    /// <summary>伺服器登錄檔名（位於伺服器根目錄）</summary>
    public const string RegistryFileName = "servers.json";

    /// <summary>管理工具內部項目（墓碑、暫存）之名稱前綴，不可作為伺服器名稱</summary>
    public const string InternalPrefix = ".msm-";

    /// <summary>標準伺服器屬性檔名</summary>
    public const string ServerPropertiesFileName = "server.properties";

    /// <summary>終端使用者授權合約檔名</summary>
    public const string EulaFileName = "eula.txt";

    /// <summary>管理員名單檔名</summary>
    public const string OpsFileName = "ops.json";

    /// <summary>白名單檔名</summary>
    public const string WhitelistFileName = "whitelist.json";

    /// <summary>玩家封鎖名單檔名</summary>
    public const string BannedPlayersFileName = "banned-players.json";

    /// <summary>IP 封鎖名單檔名</summary>
    public const string BannedIpsFileName = "banned-ips.json";

    /// <summary>玩家快取索引檔名</summary>
    public const string UserCacheFileName = "usercache.json";

    /// <summary>Forge / NeoForge JVM 自訂參數檔名</summary>
    public const string UserJvmArgsFileName = "user_jvm_args.txt";

    /// <summary>Windows 標準啟動批次檔名</summary>
    public const string StartServerBatFileName = "start_server.bat";
}
