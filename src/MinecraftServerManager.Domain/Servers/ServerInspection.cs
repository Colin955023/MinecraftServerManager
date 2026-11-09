namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器內容快照與健全度檢查結果
/// </summary>
public sealed record ServerInspection
{
    public required string Path { get; init; }
    public bool IsCandidate { get; init; }
    public string LoaderType { get; init; } = "unknown";
    public string MinecraftVersion { get; init; } = "unknown";
    public string LoaderVersion { get; init; } = "unknown";
    public ServerLaunchTarget LaunchTarget { get; init; } = ServerLaunchTarget.None();
    public int MemoryMaxMb { get; init; } = ServerDefaults.DefaultMemoryMaxMb;
    public int? MemoryMinMb { get; init; }
}
