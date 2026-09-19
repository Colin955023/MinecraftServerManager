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
        JvmArgs = Common.CollectionUtilities.ToReadOnlyList(jvmArgs);
        BackupPath = backupPath ?? string.Empty;
    }
}
