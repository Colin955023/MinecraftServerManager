namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 待安裝的線上模組項目
/// </summary>
public sealed record PendingOnlineInstall
{
    public string ProjectId { get; }
    public string ProjectName { get; }
    public OnlineModVersion Version { get; }
    public OnlineModCompatibilityReport? Report { get; }
    public string HomepageUrl { get; }
    public string SourceUrl { get; }
    public string ServerSide { get; }
    public string ClientSide { get; }

    public PendingOnlineInstall(
        string projectId,
        string projectName,
        OnlineModVersion version,
        OnlineModCompatibilityReport? report = null,
        string homepageUrl = "",
        string sourceUrl = "",
        string serverSide = "",
        string clientSide = "")
    {
        ProjectId = projectId ?? string.Empty;
        ProjectName = projectName ?? string.Empty;
        Version = version ?? throw new ArgumentNullException(nameof(version));
        Report = report;
        HomepageUrl = homepageUrl ?? string.Empty;
        SourceUrl = sourceUrl ?? string.Empty;
        ServerSide = serverSide ?? string.Empty;
        ClientSide = clientSide ?? string.Empty;
    }
}
