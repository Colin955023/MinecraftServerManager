namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組資訊（Modrinth 等遠端來源搜尋與探索結果快照）
/// </summary>
public sealed record OnlineModInfo
{
    public string ProjectId { get; }
    public string Slug { get; }
    public string Name { get; }
    public string Author { get; }
    public string Description { get; }
    public string LatestVersion { get; }
    public int DownloadCount { get; }
    public string HomepageUrl { get; }
    public string Url { get; }
    public IReadOnlyList<string> Categories { get; }
    public IReadOnlyList<string> Versions { get; }
    public string ServerSide { get; }
    public string ClientSide { get; }
    public string Source { get; }
    public bool Available { get; }

    public string Id => ProjectId;
    public string Title => Name;
    public int Downloads => DownloadCount;
    public string IconUrl { get; }
    public IReadOnlyList<string> Loaders => Categories;

    public OnlineModInfo(
        string projectId,
        string slug,
        string name,
        string author,
        string description = "",
        string latestVersion = "",
        int downloadCount = 0,
        string homepageUrl = "",
        string url = "",
        string iconUrl = "",
        IEnumerable<string>? categories = null,
        IEnumerable<string>? versions = null,
        string serverSide = "",
        string clientSide = "",
        string source = "modrinth",
        bool available = true)
    {
        ProjectId = projectId ?? string.Empty;
        Slug = slug ?? string.Empty;
        Name = name ?? string.Empty;
        Author = author ?? string.Empty;
        Description = description ?? string.Empty;
        LatestVersion = latestVersion ?? string.Empty;
        DownloadCount = downloadCount;
        HomepageUrl = homepageUrl ?? string.Empty;
        Url = url ?? string.Empty;
        IconUrl = !string.IsNullOrWhiteSpace(iconUrl) ? iconUrl : Url;
        Categories = (categories ?? []).ToArray();
        Versions = (versions ?? []).ToArray();
        ServerSide = serverSide ?? string.Empty;
        ClientSide = clientSide ?? string.Empty;
        Source = source ?? "modrinth";
        Available = available;
    }
}
