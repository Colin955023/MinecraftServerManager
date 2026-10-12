namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組資訊（Modrinth 等遠端來源搜尋與探索結果快照）
/// </summary>
public sealed record OnlineModInfo
{
    public string ProjectId { get; init; }
    public string Slug { get; init; }
    public string Name { get; init; }
    public string Author { get; init; }
    public string Description { get; init; }
    public string LatestVersion { get; init; }
    public int DownloadCount { get; init; }
    public string HomepageUrl { get; init; }
    public string Url { get; init; }
    public IReadOnlyList<string> Categories { get; init; }
    public IReadOnlyList<string> Versions { get; init; }
    public string ServerSide { get; init; }
    public string ClientSide { get; init; }
    public string Source { get; init; }
    public bool Available { get; init; }

    public string Id => ProjectId;
    public string Title => Name;
    public int Downloads => DownloadCount;
    public string IconUrl { get; init; }
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
        Categories = [.. categories ?? []];
        Versions = [.. versions ?? []];
        ServerSide = serverSide ?? string.Empty;
        ClientSide = clientSide ?? string.Empty;
        Source = source ?? "modrinth";
        Available = available;
    }
}
