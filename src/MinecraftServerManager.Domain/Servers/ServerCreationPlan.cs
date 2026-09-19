using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器建立計畫中的警告項目
/// </summary>
public sealed record ServerCreationWarning(string Message);

/// <summary>
/// 完成驗證後可交由交易執行器提交的不可變建立計畫
/// </summary>
public sealed record ServerCreationPlan
{
    public string TransactionId { get; }
    public ServerName Name { get; }
    public MinecraftVersion MinecraftVersion { get; }
    public LoaderKind LoaderType { get; }
    public string LoaderVersion { get; }
    public int MemoryMaxMb { get; }
    public int? MemoryMinMb { get; }
    public IReadOnlyList<string> JvmArgs { get; }
    public IReadOnlyDictionary<string, string> Properties { get; }
    public string FinalPath { get; }
    public string StagingPath { get; }
    public string? UserJavaPath { get; }
    public IReadOnlyList<ServerCreationWarning> Warnings { get; }
    public string RegistryRevision { get; }

    public ServerCreationPlan(
        string transactionId,
        ServerName name,
        MinecraftVersion minecraftVersion,
        LoaderKind loaderType,
        string loaderVersion,
        int memoryMaxMb,
        int? memoryMinMb,
        IEnumerable<string> jvmArgs,
        IEnumerable<KeyValuePair<string, string>> properties,
        string finalPath,
        string stagingPath,
        string? userJavaPath = null,
        IEnumerable<ServerCreationWarning>? warnings = null,
        string registryRevision = "")
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(transactionId);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(memoryMaxMb);

        if (memoryMinMb is <= 0)
        {
            ArgumentOutOfRangeException.ThrowIfNegativeOrZero(memoryMinMb.Value, nameof(memoryMinMb));
        }

        if (memoryMinMb > memoryMaxMb)
        {
            throw new ArgumentException("最小記憶體不可大於最大記憶體", nameof(memoryMinMb));
        }

        TransactionId = transactionId;
        Name = name;
        MinecraftVersion = minecraftVersion;
        LoaderType = loaderType;
        LoaderVersion = loaderVersion ?? string.Empty;
        MemoryMaxMb = memoryMaxMb;
        MemoryMinMb = memoryMinMb;
        JvmArgs = (jvmArgs ?? []).ToArray();
        Properties = new Dictionary<string, string>(properties ?? []);
        FinalPath = finalPath ?? string.Empty;
        StagingPath = stagingPath ?? string.Empty;
        UserJavaPath = userJavaPath;
        Warnings = (warnings ?? []).ToArray();
        RegistryRevision = registryRevision ?? string.Empty;
    }

    public static ServerCreationPlan Create(
        ServerName name,
        MinecraftVersion minecraftVersion,
        LoaderKind loaderType,
        string loaderVersion = "",
        int memoryMaxMb = 2048,
        int? memoryMinMb = null,
        IEnumerable<string>? jvmArgs = null,
        IEnumerable<KeyValuePair<string, string>>? properties = null,
        string finalPath = "",
        string stagingPath = "",
        string? userJavaPath = null,
        string transactionId = "") =>
        new(
            string.IsNullOrWhiteSpace(transactionId) ? Guid.NewGuid().ToString("N") : transactionId,
            name,
            minecraftVersion,
            loaderType,
            loaderVersion,
            memoryMaxMb,
            memoryMinMb,
            jvmArgs ?? [],
            properties ?? [],
            finalPath,
            stagingPath,
            userJavaPath);

    /// <summary>
    /// 建立指定交易路徑使用的伺服器設定
    /// </summary>
    public ServerConfig BuildConfig(string path)
    {
        return new ServerConfig(
            Name,
            MinecraftVersion,
            LoaderType,
            LoaderVersion,
            MemoryMaxMb,
            MemoryMinMb,
            path: path,
            jvmArgs: JvmArgs
        );
    }
}
