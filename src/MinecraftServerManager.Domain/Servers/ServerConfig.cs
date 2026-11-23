using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>伺服器核心組態（不可變且經建構驗證）</summary>
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
        if (!name.IsValid)
        {
            throw new ArgumentException("伺服器名稱未初始化", nameof(name));
        }

        if (!minecraftVersion.IsValid)
        {
            throw new ArgumentException("Minecraft 版本未初始化", nameof(minecraftVersion));
        }

        if (!Enum.IsDefined(loaderType))
        {
            throw new ArgumentOutOfRangeException(nameof(loaderType), loaderType, "未定義的載入器類型");
        }

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
        JvmArgs = jvmArgs is null ? [] : [.. jvmArgs.Where(static arg => arg is not null)];
        BackupPath = backupPath ?? string.Empty;
    }

    /// <summary>比較所有欄位，JvmArgs 依內容比對</summary>
    public bool Equals(ServerConfig? other) =>
        other is not null
        && (ReferenceEquals(this, other)
            || (Name == other.Name
                && MinecraftVersion == other.MinecraftVersion
                && LoaderType == other.LoaderType
                && string.Equals(LoaderVersion, other.LoaderVersion, StringComparison.Ordinal)
                && MemoryMaxMb == other.MemoryMaxMb
                && MemoryMinMb == other.MemoryMinMb
                && string.Equals(Path, other.Path, StringComparison.Ordinal)
                && string.Equals(BackupPath, other.BackupPath, StringComparison.Ordinal)
                && JvmArgs.SequenceEqual(other.JvmArgs, StringComparer.Ordinal)));

    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(Name);
        hash.Add(MinecraftVersion);
        hash.Add(LoaderType);
        hash.Add(LoaderVersion, StringComparer.Ordinal);
        hash.Add(MemoryMaxMb);
        hash.Add(MemoryMinMb);
        hash.Add(Path, StringComparer.Ordinal);
        hash.Add(BackupPath, StringComparer.Ordinal);
        foreach (string arg in JvmArgs)
        {
            hash.Add(arg, StringComparer.Ordinal);
        }

        return hash.ToHashCode();
    }

    /// <summary>複製並替換伺服器路徑（經建構子重新驗證）</summary>
    public ServerConfig WithPath(string path) =>
        new(Name, MinecraftVersion, LoaderType, LoaderVersion, MemoryMaxMb, MemoryMinMb, path, JvmArgs, BackupPath);

    /// <summary>複製並替換記憶體設定（經建構子重新驗證）</summary>
    public ServerConfig WithMemory(int memoryMaxMb, int? memoryMinMb) =>
        new(Name, MinecraftVersion, LoaderType, LoaderVersion, memoryMaxMb, memoryMinMb, Path, JvmArgs, BackupPath);

    /// <summary>複製並替換備份路徑</summary>
    public ServerConfig WithBackupPath(string backupPath) =>
        new(Name, MinecraftVersion, LoaderType, LoaderVersion, MemoryMaxMb, MemoryMinMb, Path, JvmArgs, backupPath);

    /// <summary>複製並替換 Minecraft 版本與載入器資訊</summary>
    public ServerConfig WithLoader(MinecraftVersion minecraftVersion, LoaderKind loaderType, string loaderVersion) =>
        new(Name, minecraftVersion, loaderType, loaderVersion, MemoryMaxMb, MemoryMinMb, Path, JvmArgs, BackupPath);
}
