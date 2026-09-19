using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// Modrinth REST API 客戶端實作
/// </summary>
public sealed class ModrinthClient(IHttpPort httpPort) : IModrinthClient
{
    private const string BaseUrl = "https://api.modrinth.com/v2";

    public async Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        string? loader = null,
        string? minecraftVersion = null,
        int limit = 20,
        int offset = 0,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var facets = new List<string> { "[\"project_type:mod\"]" };
        if (!string.IsNullOrWhiteSpace(loader) && !loader.Equals("unknown", StringComparison.OrdinalIgnoreCase) && !loader.Equals("vanilla", StringComparison.OrdinalIgnoreCase))
        {
            facets.Add($"[\"categories:{loader.Trim().ToLowerInvariant()}\"]");
        }
        if (!string.IsNullOrWhiteSpace(minecraftVersion) && !minecraftVersion.Equals("unknown", StringComparison.OrdinalIgnoreCase))
        {
            facets.Add($"[\"versions:{minecraftVersion.Trim()}\"]");
        }

        string facetsParam = Uri.EscapeDataString($"[{string.Join(",", facets)}]");
        string queryParam = Uri.EscapeDataString(query ?? string.Empty);
        string url = $"{BaseUrl}/search?query={queryParam}&facets={facetsParam}&limit={Math.Max(1, Math.Min(100, limit))}&offset={Math.Max(0, offset)}";

        string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(json))
        {
            return [];
        }

        return ParseSearchResults(json);
    }

    public async Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
        string projectIdOrSlug,
        string? loader = null,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectIdOrSlug);
        cancellationToken.ThrowIfCancellationRequested();

        var queryParams = new List<string>();
        if (!string.IsNullOrWhiteSpace(loader) && !loader.Equals("unknown", StringComparison.OrdinalIgnoreCase) && !loader.Equals("vanilla", StringComparison.OrdinalIgnoreCase))
        {
            queryParams.Add($"loaders={Uri.EscapeDataString($"[\"{loader.Trim().ToLowerInvariant()}\"]")}");
        }
        if (!string.IsNullOrWhiteSpace(minecraftVersion) && !minecraftVersion.Equals("unknown", StringComparison.OrdinalIgnoreCase))
        {
            queryParams.Add($"game_versions={Uri.EscapeDataString($"[\"{minecraftVersion.Trim()}\"]")}");
        }

        string queryString = queryParams.Count > 0 ? $"?{string.Join("&", queryParams)}" : string.Empty;
        string url = $"{BaseUrl}/project/{Uri.EscapeDataString(projectIdOrSlug.Trim())}/version{queryString}";

        string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(json))
        {
            return [];
        }

        return ParseVersionList(json);
    }

    public async Task<ModrinthVersionLookupResult?> LookupVersionByHashAsync(
        string hash,
        string algorithm = "sha512",
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(hash);
        cancellationToken.ThrowIfCancellationRequested();

        string cleanHash = hash.Trim().ToLowerInvariant();
        string url = $"{BaseUrl}/version_file/{Uri.EscapeDataString(cleanHash)}?algorithm={Uri.EscapeDataString(algorithm)}";

        string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(json))
        {
            return null;
        }

        try
        {
            using var doc = JsonDocument.Parse(json);
            var version = ParseSingleVersion(doc.RootElement);
            string projectId = doc.RootElement.TryGetProperty("project_id", out var pElem) ? pElem.GetString() ?? string.Empty : string.Empty;
            return new ModrinthVersionLookupResult(cleanHash, algorithm, projectId, version);
        }
        catch
        {
            return null;
        }
    }

    public Task<ModrinthVersionLookupResult?> GetVersionByHashAsync(
        string hash,
        string algorithm = "sha512",
        CancellationToken cancellationToken = default) =>
        LookupVersionByHashAsync(hash, algorithm, cancellationToken);

    public async Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
        IReadOnlyList<string> hashes,
        string algorithm = "sha512",
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (hashes is null || hashes.Count == 0)
        {
            return new Dictionary<string, ModrinthVersionLookupResult>();
        }

        var cleanHashes = hashes.Select(h => h.Trim().ToLowerInvariant()).Where(h => !string.IsNullOrEmpty(h)).Distinct().ToList();
        var result = new Dictionary<string, ModrinthVersionLookupResult>(StringComparer.OrdinalIgnoreCase);

        // 每批最多 50 個
        foreach (string[] chunk in cleanHashes.Chunk(50))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var payload = new { hashes = chunk, algorithm };
            string postJson = JsonCodec.Serialize(payload);

            string? responseJson = await httpPort.PostJsonAsync(new Uri($"{BaseUrl}/version_files"), postJson, cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(responseJson))
            {
                continue;
            }

            try
            {
                using var doc = JsonDocument.Parse(responseJson);
                foreach (var prop in doc.RootElement.EnumerateObject())
                {
                    string fileHash = prop.Name;
                    var version = ParseSingleVersion(prop.Value);
                    string projectId = prop.Value.TryGetProperty("project_id", out var pElem) ? pElem.GetString() ?? string.Empty : string.Empty;
                    result[fileHash] = new ModrinthVersionLookupResult(fileHash, algorithm, projectId, version);
                }
            }
            catch
            {
            }
        }

        return result;
    }

    private static List<OnlineModInfo> ParseSearchResults(string json)
    {
        var list = new List<OnlineModInfo>();
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("hits", out var hitsElem))
            {
                return list;
            }

            foreach (var hit in hitsElem.EnumerateArray())
            {
                string projectId = hit.GetProperty("project_id").GetString() ?? string.Empty;
                string slug = hit.TryGetProperty("slug", out var sElem) ? sElem.GetString() ?? string.Empty : string.Empty;
                string title = hit.TryGetProperty("title", out var tElem) ? tElem.GetString() ?? string.Empty : string.Empty;
                string author = hit.TryGetProperty("author", out var aElem) ? aElem.GetString() ?? string.Empty : string.Empty;
                string desc = hit.TryGetProperty("description", out var dElem) ? dElem.GetString() ?? string.Empty : string.Empty;
                string latestVer = hit.TryGetProperty("latest_version", out var lvElem) ? lvElem.GetString() ?? string.Empty : string.Empty;
                int downloads = hit.TryGetProperty("downloads", out var dlElem) ? dlElem.GetInt32() : 0;
                string iconUrl = hit.TryGetProperty("icon_url", out var iconElem) ? iconElem.GetString() ?? string.Empty : string.Empty;

                var categories = hit.TryGetProperty("categories", out var catElem)
                    ? catElem.EnumerateArray().Select(c => c.GetString() ?? string.Empty).ToList()
                    : new List<string>();

                var versions = hit.TryGetProperty("versions", out var verElem)
                    ? verElem.EnumerateArray().Select(v => v.GetString() ?? string.Empty).ToList()
                    : new List<string>();

                list.Add(new OnlineModInfo(
                    projectId: projectId,
                    slug: slug,
                    name: title,
                    author: author,
                    description: desc,
                    latestVersion: latestVer,
                    downloadCount: downloads,
                    homepageUrl: $"https://modrinth.com/mod/{slug}",
                    url: $"https://modrinth.com/mod/{slug}",
                    iconUrl: iconUrl,
                    categories: categories,
                    versions: versions));
            }
        }
        catch
        {
        }
        return list;
    }

    private static List<OnlineModVersion> ParseVersionList(string json)
    {
        var list = new List<OnlineModVersion>();
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
            {
                return list;
            }

            foreach (var elem in doc.RootElement.EnumerateArray())
            {
                list.Add(ParseSingleVersion(elem));
            }
        }
        catch
        {
        }
        return list;
    }

    private static OnlineModVersion ParseSingleVersion(JsonElement elem)
    {
        string id = elem.GetProperty("id").GetString() ?? string.Empty;
        string versionNumber = elem.TryGetProperty("version_number", out var vn) ? vn.GetString() ?? string.Empty : string.Empty;
        string name = elem.TryGetProperty("name", out var n) ? n.GetString() ?? versionNumber : versionNumber;
        string versionType = elem.TryGetProperty("version_type", out var vt) ? vt.GetString() ?? "release" : "release";
        string datePublished = elem.TryGetProperty("date_published", out var dp) ? dp.GetString() ?? string.Empty : string.Empty;
        string changelog = elem.TryGetProperty("changelog", out var cl) ? cl.GetString() ?? string.Empty : string.Empty;

        var gameVersions = elem.TryGetProperty("game_versions", out var gv)
            ? gv.EnumerateArray().Select(v => v.GetString() ?? string.Empty).ToList()
            : new List<string>();

        var loaders = elem.TryGetProperty("loaders", out var ld)
            ? ld.EnumerateArray().Select(l => l.GetString() ?? string.Empty).ToList()
            : new List<string>();

        var files = new List<ModFile>();
        if (elem.TryGetProperty("files", out var filesElem))
        {
            foreach (var f in filesElem.EnumerateArray())
            {
                string url = f.GetProperty("url").GetString() ?? string.Empty;
                string filename = f.GetProperty("filename").GetString() ?? string.Empty;
                bool primary = f.TryGetProperty("primary", out var pr) && pr.GetBoolean();
                long size = f.TryGetProperty("size", out var sz) ? sz.GetInt64() : 0;
                var hashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                if (f.TryGetProperty("hashes", out var hashesElem))
                {
                    foreach (var h in hashesElem.EnumerateObject())
                    {
                        hashes[h.Name] = h.Value.GetString() ?? string.Empty;
                    }
                }
                files.Add(new ModFile(filename, url, primary, size, hashes));
            }
        }

        var dependencies = new List<OnlineModDependency>();
        if (elem.TryGetProperty("dependencies", out var depElem))
        {
            foreach (var d in depElem.EnumerateArray())
            {
                string? vId = d.TryGetProperty("version_id", out var vi) ? vi.GetString() : null;
                string? pId = d.TryGetProperty("project_id", out var pi) ? pi.GetString() : null;
                string? fn = d.TryGetProperty("file_name", out var fne) ? fne.GetString() : null;
                string depTypeStr = d.TryGetProperty("dependency_type", out var dt) ? dt.GetString() ?? "required" : "required";
                var depType = depTypeStr switch
                {
                    "optional" => ModDependencyType.Optional,
                    "incompatible" => ModDependencyType.Incompatible,
                    "embedded" => ModDependencyType.Embedded,
                    _ => ModDependencyType.Required
                };
                dependencies.Add(new OnlineModDependency(vId, pId, fn, depType));
            }
        }

        return new OnlineModVersion(id, versionNumber, name, gameVersions, loaders, versionType, datePublished, changelog, files, dependencies);
    }
}
