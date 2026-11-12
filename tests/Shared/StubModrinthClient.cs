using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.TestSupport;

/// <summary>測試用共用 Modrinth API 用戶端替身</summary>
internal sealed class StubModrinthClient : IModrinthClient
{
    public Dictionary<string, IReadOnlyList<OnlineModVersion>> Versions { get; } = new(StringComparer.OrdinalIgnoreCase);

    public Dictionary<string, string> Titles { get; } = new(StringComparer.OrdinalIgnoreCase);

    public Dictionary<string, ModrinthVersionLookupResult> HashLookups { get; } = new(StringComparer.OrdinalIgnoreCase);

    public IReadOnlyList<OnlineModInfo> SearchResults { get; set; } = [];

    public List<string> RequestedProjects { get; } = [];

    public Action? OnSearchCalled { get; set; }

    public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
        string projectIdOrSlug,
        string? loader = null,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default)
    {
        RequestedProjects.Add(projectIdOrSlug);
        return Task.FromResult(Versions.TryGetValue(projectIdOrSlug, out var list) ? list : []);
    }

    public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        string? loader = null,
        string? minecraftVersion = null,
        int limit = 20,
        int offset = 0,
        string index = "relevance",
        CancellationToken cancellationToken = default)
    {
        OnSearchCalled?.Invoke();
        return Task.FromResult(SearchResults);
    }

    public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
        IReadOnlyList<string> hashes,
        string algorithm = "sha512",
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
