namespace MinecraftServerManager.Domain.Mods;

/// <summary>本機已安裝模組的中繼資料與雜湊資訊</summary>
public sealed record LocalModInfo
{
    public string Id { get; init => field = value ?? string.Empty; } = string.Empty;
    public string Name { get; init => field = value ?? string.Empty; } = string.Empty;
    public string FileName { get; init => field = value ?? string.Empty; } = string.Empty;
    public string Version { get; init => field = value ?? string.Empty; } = string.Empty;
    public string MinecraftVersion { get; init => field = value ?? string.Empty; } = string.Empty;
    public string LoaderType { get; init => field = value ?? string.Empty; } = string.Empty;
    public string Description { get; init => field = value ?? string.Empty; } = string.Empty;
    public string Author { get; init => field = value ?? string.Empty; } = string.Empty;
    public ModPlatform Platform { get; init; } = ModPlatform.Local;
    public string PlatformId { get; init => field = value ?? string.Empty; } = string.Empty;
    public string PlatformSlug { get; init => field = value ?? string.Empty; } = string.Empty;
    public ModStatus Status { get; init; } = ModStatus.Enabled;
    public long FileSize { get; init; }
    public double FileMtime { get; init; }
    public string CurrentHash { get; init => field = value ?? string.Empty; } = string.Empty;
    public string HashAlgorithm { get; init => field = value ?? string.Empty; } = string.Empty;
    public IReadOnlyList<string> Dependencies { get; init => field = value ?? []; } = [];

    public LocalModInfo()
    {
    }

    public LocalModInfo(
        string id,
        string name,
        string fileName,
        string version,
        string minecraftVersion,
        string loaderType,
        string description = "",
        string author = "",
        ModPlatform platform = ModPlatform.Local,
        string platformId = "",
        string platformSlug = "",
        ModStatus status = ModStatus.Enabled,
        long fileSize = 0,
        double fileMtime = 0.0,
        string currentHash = "",
        string hashAlgorithm = "",
        IEnumerable<string>? dependencies = null)
    {
        Id = id;
        Name = name;
        FileName = fileName;
        Version = version;
        MinecraftVersion = minecraftVersion;
        LoaderType = loaderType;
        Description = description;
        Author = author;
        Platform = platform;
        PlatformId = platformId;
        PlatformSlug = platformSlug;
        Status = status;
        FileSize = fileSize;
        FileMtime = fileMtime;
        CurrentHash = currentHash;
        HashAlgorithm = hashAlgorithm;
        Dependencies = [.. dependencies ?? []];
    }

    /// <summary>回傳補上平台專案識別碼的副本（供以官方專案識別碼比對相依使用）</summary>
    public LocalModInfo WithPlatformId(string platformId) => this with { PlatformId = platformId };
}
