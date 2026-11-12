using MinecraftServerManager.Infrastructure.Logging;
using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>Modrinth REST API 用戶端實作</summary>
public sealed class ModrinthClient(IHttpPort httpPort) : IModrinthClient
{
    private static string GetStringOrEmpty(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out var value) ? value.GetString() ?? string.Empty : string.Empty;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModrinthClient));
    private const string BaseUrl = "https://api.modrinth.com/v2";
    private static readonly string[] ProjectTypeFacet = ["project_type:mod"];
    private readonly ConcurrentDictionary<string, string> _projectTitleCache = new(StringComparer.OrdinalIgnoreCase);
    private static readonly string[] ServerSideFacet = ["server_side:required", "server_side:optional"];

    public async Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        string? loader = null,
        string? minecraftVersion = null,
        int limit = 20,
        int offset = 0,
        string index = "relevance",
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var facets = new List<string[]>
        {
            ProjectTypeFacet,
            ServerSideFacet
        };
        if (!string.IsNullOrWhiteSpace(loader) && !loader.Equals("unknown", StringComparison.OrdinalIgnoreCase) && !loader.Equals("vanilla", StringComparison.OrdinalIgnoreCase))
        {
            facets.Add([$"categories:{loader.Trim().ToLowerInvariant()}"]);
        }
        if (!string.IsNullOrWhiteSpace(minecraftVersion) && !minecraftVersion.Equals("unknown", StringComparison.OrdinalIgnoreCase))
        {
            facets.Add([$"versions:{minecraftVersion.Trim()}"]);
        }

        string facetsParam = Uri.EscapeDataString(JsonCodec.Serialize(facets.ToArray()));
        string queryParam = Uri.EscapeDataString(query ?? string.Empty);
        string indexParam = Uri.EscapeDataString(string.IsNullOrWhiteSpace(index) ? "relevance" : index.Trim());
        string url = $"{BaseUrl}/search?query={queryParam}&facets={facetsParam}&index={indexParam}&limit={Math.Clamp(limit, 1, 100)}&offset={Math.Max(0, offset)}";

        string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(json))
        {
            return [];
        }

        var results = ParseSearchResults(json);
        if (results.Count == 0)
        {
            return results;
        }

        var versionIds = results
            .Select(static m => m.LatestVersion)
            .Where(static id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (versionIds.Count > 0)
        {
            var versionMap = await FetchVersionNumbersBatchAsync(versionIds, cancellationToken).ConfigureAwait(false);
            if (versionMap.Count > 0)
            {
                return [.. results.Select(m => versionMap.TryGetValue(m.LatestVersion, out string? vn) && !string.IsNullOrWhiteSpace(vn)
                    ? m with { LatestVersion = vn }
                    : m)];
            }
        }

        return results;
    }

    private async Task<Dictionary<string, string>> FetchVersionNumbersBatchAsync(
        IReadOnlyList<string> versionIds,
        CancellationToken cancellationToken)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (string[] chunk in versionIds.Chunk(50))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                string idsParam = Uri.EscapeDataString(JsonCodec.Serialize(chunk));
                string url = $"{BaseUrl}/versions?ids={idsParam}";
                string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
                if (string.IsNullOrWhiteSpace(json))
                {
                    continue;
                }

                using var doc = JsonCodec.ParseDocument(json);
                if (doc.RootElement.ValueKind == JsonValueKind.Array)
                {
                    foreach (var elem in doc.RootElement.EnumerateArray())
                    {
                        if (elem.TryGetProperty("id", out var idProp) &&
                            elem.TryGetProperty("version_number", out var vnProp))
                        {
                            string? id = idProp.GetString();
                            string? vn = vnProp.GetString();
                            if (!string.IsNullOrWhiteSpace(id) && !string.IsNullOrWhiteSpace(vn))
                            {
                                result[id] = vn;
                            }
                        }
                    }
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "批次取得專案最新版本失敗");
            }
        }

        return result;
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
            queryParams.Add($"loaders={Uri.EscapeDataString(JsonCodec.Serialize(new[] { loader.Trim().ToLowerInvariant() }))}");
        }
        if (!string.IsNullOrWhiteSpace(minecraftVersion) && !minecraftVersion.Equals("unknown", StringComparison.OrdinalIgnoreCase))
        {
            queryParams.Add($"game_versions={Uri.EscapeDataString(JsonCodec.Serialize(new[] { minecraftVersion.Trim() }))}");
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

    public async Task<IReadOnlyDictionary<string, string>> GetProjectTitlesAsync(
        IReadOnlyCollection<string> projectIdsOrSlugs,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(projectIdsOrSlugs);

        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var pending = new List<string>();
        foreach (string key in projectIdsOrSlugs.Where(static k => !string.IsNullOrWhiteSpace(k)).Select(static k => k.Trim()).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (_projectTitleCache.TryGetValue(key, out string? cached))
            {
                result[key] = cached;
            }
            else
            {
                pending.Add(key);
            }
        }

        foreach (string[] chunk in pending.Chunk(50))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                string idsParam = Uri.EscapeDataString(JsonCodec.Serialize(chunk));
                string? json = await httpPort.GetTextAsync(new Uri($"{BaseUrl}/projects?ids={idsParam}"), cancellationToken).ConfigureAwait(false);
                if (string.IsNullOrWhiteSpace(json))
                {
                    continue;
                }

                using var doc = JsonCodec.ParseDocument(json);
                if (doc.RootElement.ValueKind != JsonValueKind.Array)
                {
                    continue;
                }

                foreach (var project in doc.RootElement.EnumerateArray())
                {
                    string title = GetStringOrEmpty(project, "title");
                    if (title.Length == 0)
                    {
                        continue;
                    }

                    // 呼叫端可能傳入 ID 或 slug，兩者皆建立對應
                    foreach (string key in new[] { GetStringOrEmpty(project, "id"), GetStringOrEmpty(project, "slug") })
                    {
                        if (key.Length > 0)
                        {
                            _projectTitleCache[key] = title;
                            result[key] = title;
                        }
                    }
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "批次取得專案名稱失敗，改以代碼顯示");
            }
        }

        return result;
    }

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

        var cleanHashes = hashes.Select(static h => h.Trim().ToLowerInvariant()).Where(static h => !string.IsNullOrEmpty(h)).Distinct().ToList();
        var result = new Dictionary<string, ModrinthVersionLookupResult>(StringComparer.OrdinalIgnoreCase);

        // 每批最多 50 個
        foreach (string[] chunk in cleanHashes.Chunk(50))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var payload = new ModrinthVersionFilesRequest(chunk, algorithm);
            string postJson = JsonCodec.Serialize(payload);

            string? responseJson = await httpPort.PostJsonAsync(new Uri($"{BaseUrl}/version_files"), postJson, cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(responseJson))
            {
                continue;
            }

            try
            {
                using var doc = JsonCodec.ParseDocument(responseJson);
                foreach (var prop in doc.RootElement.EnumerateObject())
                {
                    string fileHash = prop.Name;
                    var version = ParseSingleVersion(prop.Value);
                    string projectId = GetStringOrEmpty(prop.Value, "project_id");
                    result[fileHash] = new ModrinthVersionLookupResult(algorithm, projectId, version);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "批次取得專案最新版本失敗");
            }
        }

        return result;
    }

    private static List<OnlineModInfo> ParseSearchResults(string json)
    {
        var list = new List<OnlineModInfo>();
        try
        {
            using var doc = JsonCodec.ParseDocument(json);
            if (!doc.RootElement.TryGetProperty("hits", out var hitsElem))
            {
                return list;
            }

            foreach (var hit in hitsElem.EnumerateArray())
            {
                string projectId = hit.GetProperty("project_id").GetString() ?? string.Empty;
                string slug = GetStringOrEmpty(hit, "slug");
                string title = GetStringOrEmpty(hit, "title");
                string author = GetStringOrEmpty(hit, "author");
                string desc = GetStringOrEmpty(hit, "description");
                string latestVer = GetStringOrEmpty(hit, "latest_version");
                int downloads = hit.TryGetProperty("downloads", out var dlElem) && dlElem.TryGetInt64(out long dl) ? (int)Math.Min(dl, int.MaxValue) : 0;
                string serverSide = GetStringOrEmpty(hit, "server_side");

                if (serverSide.Equals("unsupported", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                list.Add(new OnlineModInfo(projectId, slug, title, author, desc, latestVer, downloads, serverSide));
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "解析 Modrinth 搜尋結果 JSON 失敗");
        }
        return list;
    }

    private static List<OnlineModVersion> ParseVersionList(string json)
    {
        var list = new List<OnlineModVersion>();
        try
        {
            using var doc = JsonCodec.ParseDocument(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
            {
                return list;
            }

            foreach (var elem in doc.RootElement.EnumerateArray())
            {
                try
                {
                    list.Add(ParseSingleVersion(elem));
                }
                catch (Exception ex) when (ex is KeyNotFoundException or InvalidOperationException or FormatException)
                {
                    // 單筆格式異常只略過該筆，不可讓整份版本清單遺失
                    Logger.Warning(ex, "略過格式異常的 Modrinth 版本項目");
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "解析 Modrinth 版本清單 JSON 失敗");
        }
        return list;
    }

    private static OnlineModVersion ParseSingleVersion(JsonElement elem)
    {
        string id = elem.GetProperty("id").GetString() ?? string.Empty;
        string versionNumber = GetStringOrEmpty(elem, "version_number");
        string name = elem.TryGetProperty("name", out var n) ? n.GetString() ?? versionNumber : versionNumber;
        string versionType = elem.TryGetProperty("version_type", out var vt) ? vt.GetString() ?? "release" : "release";
        string datePublished = GetStringOrEmpty(elem, "date_published");

        var gameVersions = elem.TryGetProperty("game_versions", out var gv)
            ? [.. gv.EnumerateArray().Select(static v => v.GetString() ?? string.Empty)]
            : new List<string>();

        var loaders = elem.TryGetProperty("loaders", out var ld)
            ? [.. ld.EnumerateArray().Select(static l => l.GetString() ?? string.Empty)]
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

        string projectId = GetStringOrEmpty(elem, "project_id");

        return new OnlineModVersion(id, versionNumber, name, gameVersions, loaders, versionType, datePublished, files, dependencies, projectId: projectId);
    }
}

internal sealed record ModrinthVersionFilesRequest(
    [property: JsonPropertyName("hashes")] IReadOnlyList<string> Hashes,
    [property: JsonPropertyName("algorithm")] string Algorithm);
