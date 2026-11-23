using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

public sealed class ModrinthClient : IModrinthClient
{
    private const string BaseUrl = "https://api.modrinth.com/v2";
    /// <summary>Modrinth 批次查詢單次上限</summary>
    private const int MaxBatchSize = 50;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModrinthClient));
    private static readonly string[] ProjectTypeFacet = ["project_type:mod"];
    private static readonly string[] ServerSideFacet = ["server_side:required", "server_side:optional"];

    private readonly IHttpPort _httpPort;
    private readonly ConcurrentDictionary<string, string> _projectTitleCache = new(StringComparer.OrdinalIgnoreCase);

    public ModrinthClient(IHttpPort httpPort)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        _httpPort = httpPort;
    }

    public async Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        LoaderKind? loader = null,
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
        if (loader is { } loaderKind && loaderKind is not (LoaderKind.Unknown or LoaderKind.Vanilla))
        {
            facets.Add([$"categories:{LoaderKinds.ToModrinthId(loaderKind)}"]);
        }
        if (MinecraftVersion.TryParse(minecraftVersion, out var parsedVersion))
        {
            facets.Add([$"versions:{parsedVersion.Value}"]);
        }

        string facetsParam = Uri.EscapeDataString(JsonCodec.Serialize(facets.ToArray()));
        string queryParam = Uri.EscapeDataString(query ?? string.Empty);
        string indexParam = Uri.EscapeDataString(string.IsNullOrWhiteSpace(index) ? "relevance" : index.Trim());
        string url = $"{BaseUrl}/search?query={queryParam}&facets={facetsParam}&index={indexParam}&limit={Math.Clamp(limit, 1, 100)}&offset={Math.Max(0, offset)}";

        using var searchDoc = await GetDocumentAsync(url, cancellationToken).ConfigureAwait(false);
        if (searchDoc is null)
        {
            return [];
        }

        var results = ParseSearchResults(searchDoc.RootElement);
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

    /// <summary>依 <see cref="MaxBatchSize"/> 分批執行批次非同步查詢並處理例外</summary>
    private static async Task ExecuteBatchedAsync<TItem>(
        IEnumerable<TItem> items,
        Func<TItem[], CancellationToken, Task> processBatchAsync,
        string warningMessage,
        CancellationToken cancellationToken)
    {
        foreach (TItem[] chunk in items.Chunk(MaxBatchSize))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                await processBatchAsync(chunk, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, warningMessage);
            }
        }
    }

    private async Task<Dictionary<string, string>> FetchVersionNumbersBatchAsync(
        IReadOnlyList<string> versionIds,
        CancellationToken cancellationToken)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        await ExecuteBatchedAsync(
            versionIds,
            async (chunk, ct) =>
            {
                string idsParam = Uri.EscapeDataString(JsonCodec.Serialize(chunk));
                string url = $"{BaseUrl}/versions?ids={idsParam}";
                using var doc = await GetDocumentAsync(url, ct).ConfigureAwait(false);
                if (doc is null || doc.RootElement.ValueKind != JsonValueKind.Array)
                {
                    return;
                }

                foreach (var elem in doc.RootElement.EnumerateArray())
                {
                    string? id = elem.GetStringOrNull("id");
                    string? vn = elem.GetStringOrNull("version_number");
                    if (!string.IsNullOrWhiteSpace(id) && !string.IsNullOrWhiteSpace(vn))
                    {
                        result[id] = vn;
                    }
                }
            },
            "批次取得專案最新版本失敗",
            cancellationToken).ConfigureAwait(false);

        return result;
    }

    public async Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
        string projectIdOrSlug,
        LoaderKind? loader = null,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectIdOrSlug);
        cancellationToken.ThrowIfCancellationRequested();

        var queryParams = new List<string>();
        if (loader is { } loaderKind && loaderKind is not (LoaderKind.Unknown or LoaderKind.Vanilla))
        {
            queryParams.Add($"loaders={Uri.EscapeDataString(JsonCodec.Serialize<string[]>([LoaderKinds.ToModrinthId(loaderKind)]))}");
        }
        if (MinecraftVersion.TryParse(minecraftVersion, out var parsedVersion))
        {
            queryParams.Add($"game_versions={Uri.EscapeDataString(JsonCodec.Serialize<string[]>([parsedVersion.Value]))}");
        }

        string queryString = queryParams.Count > 0 ? $"?{string.Join("&", queryParams)}" : string.Empty;
        string url = $"{BaseUrl}/project/{Uri.EscapeDataString(projectIdOrSlug.Trim())}/version{queryString}";

        using var doc = await GetDocumentAsync(url, cancellationToken).ConfigureAwait(false);
        return doc is null ? [] : ParseVersionList(doc.RootElement);
    }

    public async Task<OnlineModVersion?> GetVersionAsync(string versionId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(versionId);
        cancellationToken.ThrowIfCancellationRequested();

        using var doc = await GetDocumentAsync($"{BaseUrl}/version/{Uri.EscapeDataString(versionId.Trim())}", cancellationToken).ConfigureAwait(false);
        if (doc is null || doc.RootElement.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        var version = ParseVersionOrNull(doc.RootElement);
        if (version is null)
        {
            Logger.Warning("Modrinth 版本 {VersionId} 格式異常", versionId);
        }

        return version;
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

        await ExecuteBatchedAsync(
            pending,
            async (chunk, ct) =>
            {
                string idsParam = Uri.EscapeDataString(JsonCodec.Serialize(chunk));
                using var doc = await GetDocumentAsync($"{BaseUrl}/projects?ids={idsParam}", ct).ConfigureAwait(false);
                if (doc is null || doc.RootElement.ValueKind != JsonValueKind.Array)
                {
                    return;
                }

                foreach (var project in doc.RootElement.EnumerateArray())
                {
                    string title = project.GetStringOrEmpty("title");
                    if (title.Length == 0)
                    {
                        continue;
                    }

                    // 呼叫端可能傳入 ID 或 slug，兩者皆建立對應
                    CacheTitle(result, project.GetStringOrNull("id"), title);
                    CacheTitle(result, project.GetStringOrNull("slug"), title);
                }
            },
            "批次取得專案名稱失敗，改以代碼顯示",
            cancellationToken).ConfigureAwait(false);

        return result;
    }

    private void CacheTitle(Dictionary<string, string> result, string? key, string title)
    {
        if (!string.IsNullOrEmpty(key))
        {
            _projectTitleCache[key] = title;
            result[key] = title;
        }
    }

    public async Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
        IReadOnlyList<string> hashes,
        string algorithm = ModHelpers.PreferredHashAlgorithm,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (hashes is null || hashes.Count == 0)
        {
            return new Dictionary<string, ModrinthVersionLookupResult>();
        }

        var cleanHashes = hashes.Select(static h => h.Trim().ToLowerInvariant()).Where(static h => !string.IsNullOrEmpty(h)).Distinct().ToList();
        var result = new Dictionary<string, ModrinthVersionLookupResult>(StringComparer.OrdinalIgnoreCase);

        await ExecuteBatchedAsync(
            cleanHashes,
            async (chunk, ct) =>
            {
                var payload = new ModrinthVersionFilesRequest(chunk, algorithm);
                string postJson = JsonCodec.Serialize(payload);

                using var response = await _httpPort.PostJsonAsync(new Uri($"{BaseUrl}/version_files"), postJson, ct).ConfigureAwait(false);
                if (!response.IsSuccess)
                {
                    LogFailedResponse(response, "version_files");
                    return;
                }

                var root = response.Payload!.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                {
                    Logger.Warning("Modrinth 雜湊查詢回應格式異常: {ValueKind}", root.ValueKind);
                    return;
                }

                foreach (var prop in root.EnumerateObject())
                {
                    // 單筆格式異常只略過該筆
                    var version = ParseVersionOrNull(prop.Value);
                    if (version is null)
                    {
                        Logger.Warning("略過格式異常的雜湊查詢結果: {Hash}", prop.Name);
                        continue;
                    }

                    result[prop.Name] = new ModrinthVersionLookupResult(algorithm, version.ProjectId, version);
                }
            },
            "批次依雜湊查詢 Modrinth 版本失敗",
            cancellationToken).ConfigureAwait(false);

        return result;
    }

    /// <summary>GET 並解析 JSON；非成功回應回傳 null，<c>not_found</c> 以外的失敗記錄警告</summary>
    private async Task<JsonDocument?> GetDocumentAsync(string url, CancellationToken cancellationToken)
    {
        var response = await _httpPort.GetJsonDocumentAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (response.IsSuccess)
        {
            return response.Payload;
        }

        LogFailedResponse(response, url);
        response.Dispose();
        return null;
    }

    private static void LogFailedResponse(HttpJsonResponse<JsonDocument> response, string target)
    {
        switch (response.ErrorKind)
        {
            case "not_found":
                return;
            case "rate_limited":
                // HTTP 層已依 Retry-After 重試，仍受限代表短時間請求過多
                Logger.Warning("Modrinth 請求頻率受限（HTTP 429），已達重試上限: {Target}", target);
                return;
            default:
                Logger.Warning("Modrinth 請求失敗: {Target}，狀態碼 {StatusCode}，類型 {ErrorKind}", target, response.StatusCode, response.ErrorKind);
                return;
        }
    }

    private static List<OnlineModInfo> ParseSearchResults(JsonElement root)
    {
        var list = new List<OnlineModInfo>();
        try
        {
            if (!root.TryGetProperty("hits", JsonValueKind.Array, out var hitsElem))
            {
                return list;
            }

            foreach (var hit in hitsElem.EnumerateArray())
            {
                // 單筆格式異常只略過該筆
                string projectId = hit.GetStringOrEmpty("project_id");
                if (projectId.Length == 0)
                {
                    continue;
                }

                string slug = hit.GetStringOrEmpty("slug");
                string title = hit.GetStringOrEmpty("title");
                string author = hit.GetStringOrEmpty("author");
                string desc = hit.GetStringOrEmpty("description");
                string latestVer = hit.GetStringOrEmpty("latest_version");
                long downloads = hit.TryGetProperty("downloads", JsonValueKind.Number, out var dlElem) && dlElem.TryGetInt64(out long dl) ? Math.Max(0, dl) : 0;
                string serverSide = hit.GetStringOrEmpty("server_side");

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

    private static List<OnlineModVersion> ParseVersionList(JsonElement root)
    {
        var list = new List<OnlineModVersion>();
        try
        {
            if (root.ValueKind != JsonValueKind.Array)
            {
                return list;
            }

            foreach (var elem in root.EnumerateArray())
            {
                // 單筆格式異常只略過該筆，不可讓整份版本清單遺失
                var version = ParseVersionOrNull(elem);
                if (version is null)
                {
                    Logger.Warning("略過格式異常的 Modrinth 版本項目");
                    continue;
                }

                list.Add(version);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "解析 Modrinth 版本清單 JSON 失敗");
        }
        return list;
    }

    /// <summary>解析單一版本；缺少必要欄位（id、檔案 url/filename）時回傳 null</summary>
    private static OnlineModVersion? ParseVersionOrNull(JsonElement elem)
    {
        string? id = elem.GetStringOrNull("id");
        if (string.IsNullOrEmpty(id))
        {
            return null;
        }

        string versionNumber = elem.GetStringOrEmpty("version_number");
        string name = elem.GetStringOrNull("name") ?? versionNumber;
        string versionType = elem.GetStringOrNull("version_type") ?? "release";
        string datePublished = elem.GetStringOrEmpty("date_published");

        var files = new List<ModFile>();
        if (elem.TryGetProperty("files", JsonValueKind.Array, out var filesElem))
        {
            foreach (var f in filesElem.EnumerateArray())
            {
                string? url = f.GetStringOrNull("url");
                string? filename = f.GetStringOrNull("filename");
                if (string.IsNullOrEmpty(url) || string.IsNullOrEmpty(filename))
                {
                    return null;
                }

                bool primary = f.GetBooleanOrNull("primary") ?? false;
                long size = f.TryGetProperty("size", JsonValueKind.Number, out var sz) && sz.TryGetInt64(out long parsedSize) ? Math.Max(0, parsedSize) : 0;
                var hashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                if (f.TryGetProperty("hashes", JsonValueKind.Object, out var hashesElem))
                {
                    foreach (var h in hashesElem.EnumerateObject())
                    {
                        if (h.Value.GetStringValue() is { } hashValue)
                        {
                            hashes[h.Name] = hashValue;
                        }
                    }
                }

                files.Add(new ModFile(filename, url, primary, size, hashes));
            }
        }

        var dependencies = new List<OnlineModDependency>();
        if (elem.TryGetProperty("dependencies", JsonValueKind.Array, out var depElem))
        {
            foreach (var d in depElem.EnumerateArray())
            {
                var depType = d.GetStringOrNull("dependency_type") switch
                {
                    "optional" => ModDependencyType.Optional,
                    "incompatible" => ModDependencyType.Incompatible,
                    "embedded" => ModDependencyType.Embedded,
                    _ => ModDependencyType.Required
                };
                dependencies.Add(new OnlineModDependency(d.GetStringOrNull("version_id"), d.GetStringOrNull("project_id"), d.GetStringOrNull("file_name"), depType));
            }
        }

        return new OnlineModVersion(
            id,
            versionNumber,
            name,
            ReadStringArray(elem, "game_versions"),
            ReadStringArray(elem, "loaders"),
            versionType,
            datePublished,
            files,
            dependencies,
            projectId: elem.GetStringOrEmpty("project_id"));
    }

    private static List<string> ReadStringArray(JsonElement elem, string propertyName)
    {
        var list = new List<string>();
        if (elem.TryGetProperty(propertyName, JsonValueKind.Array, out var array))
        {
            foreach (var item in array.EnumerateArray())
            {
                if (item.GetStringValue() is { Length: > 0 } value)
                {
                    list.Add(value);
                }
            }
        }

        return list;
    }
}

internal sealed record ModrinthVersionFilesRequest(
    [property: JsonPropertyName("hashes")] IReadOnlyList<string> Hashes,
    [property: JsonPropertyName("algorithm")] string Algorithm);
