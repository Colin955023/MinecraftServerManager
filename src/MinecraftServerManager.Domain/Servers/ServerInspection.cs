namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器內容快照與健全度檢查結果
/// </summary>
public sealed record ServerInspection
{
    public string Path { get; }
    public string Revision { get; }
    public bool IsCandidate { get; }
    public string Error { get; }
    public string LoaderType { get; }
    public string MinecraftVersion { get; }
    public string LoaderVersion { get; }
    public IReadOnlyDictionary<string, string> Evidence { get; }
    public IReadOnlyList<string> Conflicts { get; }
    public ServerLaunchTarget LaunchTarget { get; }
    public int MemoryMaxMb { get; }
    public int? MemoryMinMb { get; }
    public EulaState EulaState { get; }
    public IReadOnlyList<string> MissingFiles { get; }
    public IReadOnlyList<string> Warnings { get; }
    public bool StatusReady { get; }
    public bool Launchable { get; }
    public long TotalSizeBytes { get; }

    public ServerInspection(
        string path,
        string revision,
        bool isCandidate,
        string error = "",
        string loaderType = "unknown",
        string minecraftVersion = "unknown",
        string loaderVersion = "unknown",
        IEnumerable<KeyValuePair<string, string>>? evidence = null,
        IEnumerable<string>? conflicts = null,
        ServerLaunchTarget? launchTarget = null,
        int memoryMaxMb = 2048,
        int? memoryMinMb = null,
        EulaState eulaState = EulaState.Missing,
        IEnumerable<string>? missingFiles = null,
        IEnumerable<string>? warnings = null,
        bool statusReady = false,
        bool launchable = false,
        long totalSizeBytes = 0)
    {
        TotalSizeBytes = totalSizeBytes;
        Path = path ?? string.Empty;
        Revision = revision ?? string.Empty;
        IsCandidate = isCandidate;
        Error = error ?? string.Empty;
        LoaderType = loaderType ?? "unknown";
        MinecraftVersion = minecraftVersion ?? "unknown";
        LoaderVersion = loaderVersion ?? "unknown";
        Evidence = (evidence ?? []).ToDictionary(e => e.Key, e => e.Value);
        Conflicts = (conflicts ?? []).ToArray();
        LaunchTarget = launchTarget ?? ServerLaunchTarget.None();
        MemoryMaxMb = memoryMaxMb;
        MemoryMinMb = memoryMinMb;
        EulaState = eulaState;
        MissingFiles = (missingFiles ?? []).ToArray();
        Warnings = (warnings ?? []).ToArray();
        StatusReady = statusReady;
        Launchable = launchable;
    }
}
