namespace MinecraftServerManager.Domain.Mods;

public sealed record LocalModInfo
{
    public string Id { get; }
    public string Name { get; }
    public string Filename { get; }
    public string Version { get; }
    public string MinecraftVersion { get; }
    public string LoaderType { get; }
    public string Description { get; }
    public string Author { get; }
    public ModPlatform Platform { get; }
    public string PlatformId { get; }
    public string PlatformSlug { get; }
    public ModStatus Status { get; }
    public string FilePath { get; }
    public long FileSize { get; }
    public double FileMtime { get; }
    public string CurrentHash { get; }
    public string HashAlgorithm { get; }
    public IReadOnlyList<string> Dependencies { get; }

    public LocalModInfo(
        string id,
        string name,
        string filename,
        string version,
        string minecraftVersion,
        string loaderType,
        string description = "",
        string author = "",
        ModPlatform platform = ModPlatform.Local,
        string platformId = "",
        string platformSlug = "",
        ModStatus status = ModStatus.Enabled,
        string filePath = "",
        long fileSize = 0,
        double fileMtime = 0.0,
        string currentHash = "",
        string hashAlgorithm = "",
        IEnumerable<string>? dependencies = null)
    {
        Id = id ?? string.Empty;
        Name = name ?? string.Empty;
        Filename = filename ?? string.Empty;
        Version = version ?? string.Empty;
        MinecraftVersion = minecraftVersion ?? string.Empty;
        LoaderType = loaderType ?? string.Empty;
        Description = description ?? string.Empty;
        Author = author ?? string.Empty;
        Platform = platform;
        PlatformId = platformId ?? string.Empty;
        PlatformSlug = platformSlug ?? string.Empty;
        Status = status;
        FilePath = filePath ?? string.Empty;
        FileSize = fileSize;
        FileMtime = fileMtime;
        CurrentHash = currentHash ?? string.Empty;
        HashAlgorithm = hashAlgorithm ?? string.Empty;
        Dependencies = Common.CollectionUtilities.ToReadOnlyList(dependencies);
    }
}
