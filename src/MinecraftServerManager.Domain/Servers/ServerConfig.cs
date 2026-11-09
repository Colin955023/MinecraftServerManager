using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

public sealed record ServerConfig
{
    public ServerName Name { get; }
    public MinecraftVersion MinecraftVersion { get; }
    public LoaderKind LoaderType { get; }
    public string LoaderVersion { get; }
    public int MemoryMaxMb { get; }
    public int? MemoryMinMb { get; }
    public string Path { get; }
    public IReadOnlyList<string> JvmArgs { get; }
    public string BackupPath { get; }

    public ServerConfig(
        ServerName name,
        MinecraftVersion minecraftVersion,
        LoaderKind loaderType,
        string loaderVersion,
        int memoryMaxMb,
        int? memoryMinMb = null,
        string path = "",
        IEnumerable<string>? jvmArgs = null,
        string backupPath = "")
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(memoryMaxMb);

        if (memoryMinMb is <= 0)
        {
            ArgumentOutOfRangeException.ThrowIfNegativeOrZero(memoryMinMb.Value, nameof(memoryMinMb));
        }

        if (memoryMinMb > memoryMaxMb)
        {
            throw new ArgumentException("最小記憶體不可大於最大記憶體", nameof(memoryMinMb));
        }

        Name = name;
        MinecraftVersion = minecraftVersion;
        LoaderType = loaderType;
        LoaderVersion = loaderVersion ?? string.Empty;
        MemoryMaxMb = memoryMaxMb;
        MemoryMinMb = memoryMinMb;
        Path = path ?? string.Empty;
        JvmArgs = [.. jvmArgs ?? []];
        BackupPath = backupPath ?? string.Empty;
    }

    /// <summary>
    /// 複製並替換伺服器路徑（經建構子重新驗證）
    /// </summary>
    public ServerConfig WithPath(string path) =>
        new(Name, MinecraftVersion, LoaderType, LoaderVersion, MemoryMaxMb, MemoryMinMb, path, JvmArgs, BackupPath);

    /// <summary>
    /// 複製並替換記憶體設定（經建構子重新驗證）
    /// </summary>
    public ServerConfig WithMemory(int memoryMaxMb, int? memoryMinMb) =>
        new(Name, MinecraftVersion, LoaderType, LoaderVersion, memoryMaxMb, memoryMinMb, Path, JvmArgs, BackupPath);

    /// <summary>
    /// 複製並替換備份路徑
    /// </summary>
    public ServerConfig WithBackupPath(string backupPath) =>
        new(Name, MinecraftVersion, LoaderType, LoaderVersion, MemoryMaxMb, MemoryMinMb, Path, JvmArgs, backupPath);

    /// <summary>
    /// 複製並替換 Minecraft 版本與載入器資訊
    /// </summary>
    public ServerConfig WithLoader(MinecraftVersion minecraftVersion, LoaderKind loaderType, string loaderVersion) =>
        new(Name, minecraftVersion, loaderType, loaderVersion, MemoryMaxMb, MemoryMinMb, Path, JvmArgs, BackupPath);
}
