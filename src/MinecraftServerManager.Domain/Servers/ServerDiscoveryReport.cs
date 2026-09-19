namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 候選目錄的探索失敗診斷資訊
/// </summary>
public sealed record ServerDiscoveryIssue(string Path, string Message);

/// <summary>
/// 伺服器探索成功項目、已管理項目與個別失敗診斷報告
/// </summary>
public sealed record ServerDiscoveryReport
{
    public IReadOnlyList<ServerImportInspection> Candidates { get; }
    public IReadOnlyList<ServerDiscoveryIssue> Issues { get; }
    public int ManagedCount { get; }

    public ServerDiscoveryReport(
        IEnumerable<ServerImportInspection>? candidates = null,
        IEnumerable<ServerDiscoveryIssue>? issues = null,
        int managedCount = 0)
    {
        Candidates = (candidates ?? []).ToArray();
        Issues = (issues ?? []).ToArray();
        ManagedCount = managedCount;
    }
}
