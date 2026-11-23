namespace MinecraftServerManager.Domain.Mods;

/// <summary>線上模組的單一發布版本與相依資訊</summary>
public sealed record OnlineModVersion
{
    public string VersionId { get; init => field = value ?? string.Empty; } = string.Empty;
    public string VersionNumber { get; init => field = value ?? string.Empty; } = string.Empty;
    public string DisplayName { get; init => field = value ?? string.Empty; } = string.Empty;
    public string ProjectId { get; init => field = value ?? string.Empty; } = string.Empty;
    public IReadOnlyList<string> GameVersions { get; init => field = value ?? []; } = [];
    public IReadOnlyList<string> Loaders { get; init => field = value ?? []; } = [];
    public string VersionType { get; init => field = value ?? string.Empty; } = string.Empty;
    public string DatePublished { get; init => field = value ?? string.Empty; } = string.Empty;
    public IReadOnlyList<ModFile> Files { get; init => field = value ?? []; } = [];
    public IReadOnlyList<OnlineModDependency> Dependencies { get; init => field = value ?? []; } = [];

    public OnlineModVersion(
        string versionId,
        string versionNumber,
        string displayName,
        IEnumerable<string>? gameVersions = null,
        IEnumerable<string>? loaders = null,
        string versionType = "",
        string datePublished = "",
        IEnumerable<ModFile>? files = null,
        IEnumerable<OnlineModDependency>? dependencies = null,
        string projectId = "")
    {
        VersionId = versionId;
        VersionNumber = versionNumber;
        DisplayName = displayName;
        ProjectId = projectId;
        GameVersions = [.. gameVersions ?? []];
        Loaders = [.. loaders ?? []];
        VersionType = versionType;
        DatePublished = datePublished;
        Files = files is null ? [] : [.. files.Where(static file => file is not null)];
        PrimaryFile = SelectPrimaryFile(Files);
        Dependencies = [.. dependencies ?? []];
    }

    /// <summary>主要檔案：標記 primary 者優先，其次第一個 .jar，再其次第一個檔案</summary>
    public ModFile? PrimaryFile { get; init; }

    private static ModFile? SelectPrimaryFile(IReadOnlyList<ModFile> files)
    {
        ModFile? firstJar = null;
        foreach (var file in files)
        {
            if (file.IsPrimary)
            {
                return file;
            }

            if (firstJar is null && file.FileName.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
            {
                firstJar = file;
            }
        }

        return firstJar ?? (files.Count > 0 ? files[0] : null);
    }
}
