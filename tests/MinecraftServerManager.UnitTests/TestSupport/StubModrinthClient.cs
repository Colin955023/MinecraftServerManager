using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.UnitTests.TestSupport;

internal sealed class StubModrinthClient : IModrinthClient
{
    public Dictionary<string, IReadOnlyList<OnlineModVersion>> Versions { get; } = new(StringComparer.OrdinalIgnoreCase);

    public Dictionary<string, string> Titles { get; } = new(StringComparer.OrdinalIgnoreCase);

    public Dictionary<string, ModrinthVersionLookupResult> HashLookups { get; } = new(StringComparer.OrdinalIgnoreCase);

    public List<string> RequestedProjects { get; } = [];

    /// <summary>依「專案|載入器」提供版本，優先於 <see cref="Versions"/></summary>
    public Dictionary<string, IReadOnlyList<OnlineModVersion>> LoaderVersions { get; } = new(StringComparer.OrdinalIgnoreCase);

    public List<LoaderKind?> RequestedLoaders { get; } = [];

    public Action? OnSearchCalled { get; set; }

    public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
        string projectIdOrSlug,
        LoaderKind? loader = null,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default)
    {
        RequestedProjects.Add(projectIdOrSlug);
        RequestedLoaders.Add(loader);
        if (LoaderVersions.Count > 0)
        {
            string loaderKey = loader is { } kind ? LoaderKinds.ToModrinthId(kind) : string.Empty;
            return Task.FromResult(LoaderVersions.TryGetValue($"{projectIdOrSlug}|{loaderKey}", out var byLoader) ? byLoader : []);
        }

        return Task.FromResult(Versions.TryGetValue(projectIdOrSlug, out var list) ? list : []);
    }

    public Task<OnlineModVersion?> GetVersionAsync(string versionId, CancellationToken cancellationToken = default) =>
        Task.FromResult(Versions.Values.SelectMany(static v => v).FirstOrDefault(v => string.Equals(v.VersionId, versionId, StringComparison.OrdinalIgnoreCase)));

    public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        LoaderKind? loader = null,
        string? minecraftVersion = null,
        int limit = 20,
        int offset = 0,
        string index = "relevance",
        CancellationToken cancellationToken = default)
    {
        OnSearchCalled?.Invoke();
        return Task.FromResult<IReadOnlyList<OnlineModInfo>>([]);
    }

    public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
        IReadOnlyList<string> hashes,
        string algorithm = ModHelpers.Sha512HashAlgorithm,
        CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyDictionary<string, ModrinthVersionLookupResult>>(
            HashLookups.Where(kv => hashes.Contains(kv.Key, StringComparer.OrdinalIgnoreCase))
                .ToDictionary(StringComparer.OrdinalIgnoreCase));

    public Task<IReadOnlyDictionary<string, string>> GetProjectTitlesAsync(
        IReadOnlyCollection<string> projectIdsOrSlugs,
        CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyDictionary<string, string>>(
            Titles.Where(t => projectIdsOrSlugs.Contains(t.Key, StringComparer.OrdinalIgnoreCase))
                .ToDictionary(StringComparer.OrdinalIgnoreCase));
}
