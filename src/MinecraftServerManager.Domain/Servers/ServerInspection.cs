using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>伺服器內容快照與健全度檢查結果；無法辨識之欄位為 <see cref="LoaderKind.Unknown"/> 或 null</summary>
public sealed record ServerInspection
{
    public required string Path { get; init; }
    public bool IsCandidate { get; init; }
    public LoaderKind LoaderType { get; init; } = LoaderKind.Unknown;
    public MinecraftVersion? MinecraftVersion { get; init; }
    public string? LoaderVersion { get; init; }
    public ServerLaunchTarget LaunchTarget { get; init; } = ServerLaunchTarget.None();
    public int MemoryMaxMb { get; init; } = ServerDefaults.DefaultMemoryMaxMb;
    public int? MemoryMinMb { get; init; }
}
