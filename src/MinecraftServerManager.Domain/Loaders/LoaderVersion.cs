namespace MinecraftServerManager.Domain.Loaders;

public sealed record LoaderVersion
{
    public string Version { get; }
    public string? Url { get; }
    public bool? Stable { get; }
    public string? MinecraftVersion { get; }
    public IReadOnlyList<string> GameVersions { get; }

    public LoaderVersion(
        string version,
        string? url = null,
        bool? stable = null,
        string? minecraftVersion = null,
        IEnumerable<string>? gameVersions = null)
    {
        Version = version ?? string.Empty;
        Url = url;
        Stable = stable;
        MinecraftVersion = minecraftVersion;
        GameVersions = (gameVersions ?? []).ToArray();
    }
}
