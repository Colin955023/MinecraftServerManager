namespace MinecraftServerManager.Domain.Mods;

public sealed record OnlineModVersion
{
    public string VersionId { get; }
    public string VersionNumber { get; }
    public string DisplayName { get; }
    public IReadOnlyList<string> GameVersions { get; }
    public IReadOnlyList<string> Loaders { get; }
    public string VersionType { get; }
    public string DatePublished { get; }
    public string Changelog { get; }
    public IReadOnlyList<ModFile> Files { get; }
    public IReadOnlyList<OnlineModDependency> Dependencies { get; }

    public string Id => VersionId;

    public OnlineModVersion(
        string versionId,
        string versionNumber,
        string displayName,
        IEnumerable<string>? gameVersions = null,
        IEnumerable<string>? loaders = null,
        string versionType = "",
        string datePublished = "",
        string changelog = "",
        IEnumerable<ModFile>? files = null,
        IEnumerable<OnlineModDependency>? dependencies = null)
    {
        VersionId = versionId ?? string.Empty;
        VersionNumber = versionNumber ?? string.Empty;
        DisplayName = displayName ?? string.Empty;
        GameVersions = (gameVersions ?? []).ToArray();
        Loaders = (loaders ?? []).ToArray();
        VersionType = versionType ?? string.Empty;
        DatePublished = datePublished ?? string.Empty;
        Changelog = changelog ?? string.Empty;
        Files = (files ?? []).ToArray();
        Dependencies = (dependencies ?? []).ToArray();
    }

    public ModFile? PrimaryFile
    {
        get
        {
            for (int index = 0; index < Files.Count; index++)
            {
                if (Files[index].IsPrimary)
                {
                    return Files[index];
                }
            }

            for (int index = 0; index < Files.Count; index++)
            {
                if (Files[index].Filename.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
                {
                    return Files[index];
                }
            }

            return Files.Count > 0 ? Files[0] : null;
        }
    }
}
