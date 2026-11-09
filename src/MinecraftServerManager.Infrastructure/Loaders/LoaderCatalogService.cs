using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Core.Utilities;
using System.Collections.Concurrent;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderCatalogService(IHttpPort httpPort, string cacheDirectory) : ILoaderCatalogService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LoaderCatalogService));
    private static readonly LoaderKind[] ReloadableLoaders = [LoaderKind.Fabric, LoaderKind.Quilt, LoaderKind.Forge, LoaderKind.NeoForge];
    private readonly string _cacheDir = SafeFileSystem.ResolveStableDirectory(cacheDirectory, create: true);

    private string GetMinecraftCacheFilePath() => MojangVersionCatalog.GetVersionsCachePath(_cacheDir);
    private string GetPaperCacheFilePath() => MojangVersionCatalog.GetPaperVersionsCachePath(_cacheDir);
    private string GetLoaderCacheFilePath(LoaderKind loader) => Path.Combine(_cacheDir, $"{loader.ToString().ToLowerInvariant()}_versions_cache.json");
    private readonly TimeSpan _cacheTtl = TimeSpan.FromHours(12);
    private readonly ConcurrentDictionary<(LoaderKind, string), IReadOnlyList<LoaderVersion>> _memoryLoaderCache = new();
    private IReadOnlyList<LoaderVersion>? _memoryMinecraftVersions;
    private IReadOnlyList<LoaderVersion>? _memoryPaperMinecraftVersions;

    public async Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!includeSnapshots && _memoryMinecraftVersions is { Count: > 0 })
        {
            return _memoryMinecraftVersions;
        }

        string cacheFile = GetMinecraftCacheFilePath();

        if (!includeSnapshots && IsCacheFresh(cacheFile))
        {
            var cached = MojangVersionCatalog.LoadCachedVersions(cacheFile);
            var validCached = cached.Where(IsStableOfficialRelease).ToList();
            if (validCached.Count > 0)
            {
                if (validCached.Count != cached.Count)
                {
                    MojangVersionCatalog.SaveCachedVersions(cacheFile, validCached);
                }
                var filtered = FilterMinecraftVersions(validCached, includeSnapshots: false);
                _memoryMinecraftVersions = filtered;
                return filtered;
            }
        }

        var parsed = await MojangVersionCatalog.FetchManifestAsync(httpPort, cancellationToken).ConfigureAwait(false);
        if (parsed is { Count: > 0 })
        {
            var cacheable = parsed.Where(IsStableOfficialRelease).ToList();
            MojangVersionCatalog.SaveCachedVersions(cacheFile, cacheable);
            var filtered = FilterMinecraftVersions(parsed, includeSnapshots);
            if (!includeSnapshots)
            {
                _memoryMinecraftVersions = filtered;
            }
            return filtered;
        }

        // 遠端失敗時嘗試過期快取
        Logger.Warning("抓取 Mojang 版本清單失敗，改用過期快取");
        var stale = MojangVersionCatalog.LoadCachedVersions(cacheFile);
        var validStale = stale.Where(IsStableOfficialRelease).ToList();
        if (validStale.Count == 0)
        {
            return [];
        }

        if (validStale.Count != stale.Count)
        {
            MojangVersionCatalog.SaveCachedVersions(cacheFile, validStale);
        }

        var staleFiltered = FilterMinecraftVersions(validStale, includeSnapshots);
        if (!includeSnapshots)
        {
            _memoryMinecraftVersions = staleFiltered;
        }
        return staleFiltered;
    }

    public async Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsForLoaderAsync(
        LoaderKind loader,
        bool includeSnapshots = false,
        bool forceReload = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (loader == LoaderKind.Paper)
        {
            var versions = await GetPaperMinecraftVersionsAsync(forceReload, cancellationToken).ConfigureAwait(false);
            return FilterMinecraftVersions(versions, includeSnapshots);
        }

        IReadOnlyList<LoaderVersion> baseVersions;
        if (forceReload)
        {
            _memoryMinecraftVersions = null;
            baseVersions = await ReloadAndMergeMinecraftVersionsAsync(includeSnapshots, cancellationToken).ConfigureAwait(false);
        }
        else
        {
            baseVersions = await GetMinecraftVersionsAsync(includeSnapshots, cancellationToken).ConfigureAwait(false);
        }

        if (loader is LoaderKind.Fabric or LoaderKind.Quilt)
        {
            return [.. baseVersions.Where(static v => MinecraftVersionSemantics.IsFabricCompatible(v.Version))];
        }

        return baseVersions;
    }

    public async Task<IReadOnlyList<LoaderVersion>> GetPaperMinecraftVersionsAsync(
        bool forceReload = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!forceReload && _memoryPaperMinecraftVersions is { Count: > 0 })
        {
            return _memoryPaperMinecraftVersions;
        }

        string cacheFile = GetPaperCacheFilePath();

        if (!forceReload && IsCacheFresh(cacheFile))
        {
            var cached = MojangVersionCatalog.LoadCachedVersions(cacheFile);
            var validCached = cached.Where(v => !string.IsNullOrWhiteSpace(v.Build) && v.JavaMajor is > 0).ToList();
            if (validCached.Count > 0)
            {
                if (validCached.Count != cached.Count)
                {
                    MojangVersionCatalog.SaveCachedVersions(cacheFile, validCached);
                }
                _memoryPaperMinecraftVersions = validCached;
                return validCached;
            }
        }

        try
        {
            string url = MojangVersionCatalog.PaperProjectUrl;
            var response = await httpPort.GetJsonDocumentAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
            if (response.IsSuccess && response.Payload is not null)
            {
                List<LoaderVersion> baseVersions;
                using (response.Payload)
                {
                    baseVersions = ParsePaperMinecraftVersions(response.Payload);
                }
                if (baseVersions.Count > 0)
                {
                    // 載入既有快取以比對差異（已具備 JavaMajor 與有效 Build 的版本無須重複呼叫 API）
                    var existingMap = new Dictionary<string, (int JavaMajor, string Build)>(StringComparer.OrdinalIgnoreCase);
                    if (SafeFileSystem.FileExists(cacheFile))
                    {
                        foreach (var ev in MojangVersionCatalog.LoadCachedVersions(cacheFile))
                        {
                            if (ev.JavaMajor is > 0 && !string.IsNullOrWhiteSpace(ev.Build))
                            {
                                existingMap[ev.Version] = (ev.JavaMajor.Value, ev.Build);
                            }
                        }
                    }

                    var fullVersions = new LoaderVersion?[baseVersions.Count];
                    await Parallel.ForAsync(
                        0,
                        baseVersions.Count,
                        new ParallelOptions { MaxDegreeOfParallelism = 5, CancellationToken = cancellationToken },
                        async (index, token) =>
                        {
                            var v = baseVersions[index];
                            if (existingMap.TryGetValue(v.Version, out var existing))
                            {
                                fullVersions[index] = v with { JavaMajor = existing.JavaMajor, Build = existing.Build };
                                return;
                            }

                            // 查詢 STABLE 建置清單；若無任何 STABLE 建置，直接剔除（不納入快取）
                            var builds = await FetchPaperBuildsAsync(v.Version, token, updateCache: false).ConfigureAwait(false);
                            if (builds.Count == 0 || string.IsNullOrWhiteSpace(builds[0].Version))
                            {
                                return;
                            }

                            int? javaMajor = await MojangVersionCatalog.FetchPaperJavaMajorAsync(httpPort, v.Version, token).ConfigureAwait(false);
                            fullVersions[index] = v with { JavaMajor = javaMajor, Build = builds[0].Version };
                        }).ConfigureAwait(false);

                    var result = fullVersions
                        .OfType<LoaderVersion>()
                        .OrderByDescending(v => VersionValue.ParseOrZero(v.Version))
                        .ToList();

                    MojangVersionCatalog.SaveCachedVersions(cacheFile, result);
                    _memoryPaperMinecraftVersions = result;
                    return result;
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("抓取 Paper 版本清單失敗，改用過期快取: {0}", ex.Message);
            if (SafeFileSystem.FileExists(cacheFile))
            {
                var stale = MojangVersionCatalog.LoadCachedVersions(cacheFile);
                var validStale = stale.Where(v => !string.IsNullOrWhiteSpace(v.Build) && v.JavaMajor is > 0).ToList();
                if (validStale.Count > 0)
                {
                    return validStale;
                }
            }
        }

        return [];
    }

    public async Task<IReadOnlyList<LoaderVersion>> GetLoaderVersionsAsync(
        LoaderKind loader,
        string minecraftVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(minecraftVersion);
        cancellationToken.ThrowIfCancellationRequested();

        if (loader == LoaderKind.Paper)
        {
            if (_memoryLoaderCache.TryGetValue((loader, minecraftVersion), out var memCachedPaper))
            {
                return memCachedPaper;
            }

            try
            {
                var fetched = await FetchPaperBuildsAsync(minecraftVersion, cancellationToken).ConfigureAwait(false);
                if (fetched.Count > 0)
                {
                    _memoryLoaderCache[(loader, minecraftVersion)] = fetched;
                    return fetched;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "取得 Paper 組建版本列表異常");
            }

            return [];
        }

        if (_memoryLoaderCache.TryGetValue((loader, minecraftVersion), out var memCached))
        {
            return memCached;
        }

        string cacheFile = GetLoaderCacheFilePath(loader);

        if (IsCacheFresh(cacheFile))
        {
            var cached = MojangVersionCatalog.LoadCachedVersions(cacheFile);
            var filtered = FilterLoaderByMcVersion(cached, loader, minecraftVersion);
            if (filtered.Count > 0)
            {
                _memoryLoaderCache[(loader, minecraftVersion)] = filtered;
                return filtered;
            }
        }

        try
        {
            IReadOnlyList<LoaderVersion> fetched = await FetchLoaderVersionsAsync(loader, cancellationToken).ConfigureAwait(false);

            if (fetched.Count > 0)
            {
                var pruned = PruneVersionsForCache(loader, fetched);
                MojangVersionCatalog.SaveCachedVersions(cacheFile, pruned);
                var filtered = FilterLoaderByMcVersion(pruned, loader, minecraftVersion);
                _memoryLoaderCache[(loader, minecraftVersion)] = filtered;
                return filtered;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("抓取載入器版本清單失敗，改用過期快取: {0}", ex.Message);
            if (SafeFileSystem.FileExists(cacheFile))
            {
                var stale = MojangVersionCatalog.LoadCachedVersions(cacheFile);
                var filtered = FilterLoaderByMcVersion(stale, loader, minecraftVersion);
                _memoryLoaderCache[(loader, minecraftVersion)] = filtered;
                return filtered;
            }
        }

        return [];
    }

    private static IReadOnlyList<LoaderVersion> PruneVersionsForCache(LoaderKind loader, IReadOnlyList<LoaderVersion> versions)
    {
        if (versions.Count == 0)
        {
            return versions;
        }

        if (loader is LoaderKind.Fabric or LoaderKind.Quilt)
        {
            return [.. versions
                .Where(static v => v.Stable && !ContainsPreReleaseKeyword(v.Version))
                .Take(5)];
        }

        if (loader is LoaderKind.Forge or LoaderKind.NeoForge)
        {
            return [.. versions
                .Where(static v => !string.IsNullOrWhiteSpace(v.MinecraftVersion))
                .GroupBy(static v => v.MinecraftVersion!, StringComparer.OrdinalIgnoreCase)
                .SelectMany(static g => g.OrderByDescending(VersionSortKey).Take(4))];
        }

        return versions;
    }

    private Task<IReadOnlyList<LoaderVersion>> FetchLoaderVersionsAsync(LoaderKind loader, CancellationToken cancellationToken) => loader switch
    {
        LoaderKind.Fabric => FetchMetaLoaderVersionsAsync("https://meta.fabricmc.net/v2/versions/loader", cancellationToken),
        LoaderKind.Quilt => FetchMetaLoaderVersionsAsync("https://meta.quiltmc.org/v3/versions/loader", cancellationToken),
        LoaderKind.Forge => FetchForgeVersionsAsync(cancellationToken),
        LoaderKind.NeoForge => FetchNeoForgeVersionsAsync(cancellationToken),
        _ => Task.FromResult<IReadOnlyList<LoaderVersion>>([]),
    };

    /// <summary>
    /// 取得 Fabric／Quilt meta API 之載入器版本（兩者格式相同，皆排除預發布版本）
    /// </summary>
    private async Task<IReadOnlyList<LoaderVersion>> FetchMetaLoaderVersionsAsync(string url, CancellationToken cancellationToken)
    {
        var response = await httpPort.GetJsonDocumentAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        using var doc = response.Payload;
        if (doc is null || doc.RootElement.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        var list = new List<LoaderVersion>();
        foreach (var element in doc.RootElement.EnumerateArray())
        {
            if (element.TryGetProperty("version", out var vProp) &&
                vProp.GetString() is { Length: > 0 } ver &&
                !ContainsPreReleaseKeyword(ver))
            {
                list.Add(new LoaderVersion(ver, Stable: true));
            }
        }

        return list;
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchForgeVersionsAsync(CancellationToken cancellationToken)
    {
        string url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml";
        string? xml = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        return string.IsNullOrWhiteSpace(xml) ? [] : ParseMavenMetadataXml(xml, isNeoForge: false);
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchNeoForgeVersionsAsync(CancellationToken cancellationToken)
    {
        string url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml";
        string? xml = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        return string.IsNullOrWhiteSpace(xml) ? [] : ParseMavenMetadataXml(xml, isNeoForge: true);
    }

    /// <summary>
    /// 僅保留有官方伺服器 jar 的穩定版本（供快取寫入與讀取時共用）
    /// </summary>
    private static bool IsStableOfficialRelease(LoaderVersion version) =>
        version.Stable && MojangVersionCatalog.HasOfficialServerJar(version.Version);

    public async Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.WhenAll(ReloadableLoaders.Select(loader => ReloadLoaderAsync(loader, cancellationToken))).ConfigureAwait(false);

        // 檔案快取已更新；清除記憶體快取，後續查詢才會讀到新資料
        _memoryLoaderCache.Clear();
    }

    public async Task WarmupLoadersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var staleLoaders = ReloadableLoaders
            .Where(loader => !IsCacheFresh(GetLoaderCacheFilePath(loader)))
            .ToList();

        if (staleLoaders.Count > 0)
        {
            await Task.WhenAll(staleLoaders.Select(loader => ReloadLoaderAsync(loader, cancellationToken))).ConfigureAwait(false);
        }
    }

    private async Task ReloadLoaderAsync(LoaderKind loader, CancellationToken cancellationToken)
    {
        string cacheFile = GetLoaderCacheFilePath(loader);
        try
        {
            IReadOnlyList<LoaderVersion> fetched = await FetchLoaderVersionsAsync(loader, cancellationToken).ConfigureAwait(false);
            if (fetched.Count > 0)
            {
                MojangVersionCatalog.SaveCachedVersions(cacheFile, PruneVersionsForCache(loader, fetched));
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            Logger.Warning("重新載入 {Loader} 版本清單失敗: {Message}", loader, ex.Message);
        }
    }

    public async Task<IReadOnlyList<LoaderVersion>> ReloadAndMergeMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        string cacheFile = GetMinecraftCacheFilePath();
        var existing = SafeFileSystem.FileExists(cacheFile) ? MojangVersionCatalog.LoadCachedVersions(cacheFile) : [];

        try
        {
            var fetched = await MojangVersionCatalog.FetchManifestAsync(httpPort, cancellationToken).ConfigureAwait(false);
            if (fetched is not null)
            {
                if (fetched.Count > 0)
                {
                    var existingMap = new Dictionary<string, LoaderVersion>(StringComparer.OrdinalIgnoreCase);
                    foreach (var v in existing)
                    {
                        existingMap[v.Version] = v;
                    }

                    var updatedFetched = new LoaderVersion[fetched.Count];
                    await Parallel.ForAsync(
                        0,
                        fetched.Count,
                        new ParallelOptions { MaxDegreeOfParallelism = 5, CancellationToken = cancellationToken },
                        async (index, token) =>
                        {
                            var v = fetched[index];
                            if (!v.Stable || !MinecraftVersionSemantics.IsOfficialReleaseVersion(v.Version) || string.IsNullOrWhiteSpace(v.Url))
                            {
                                updatedFetched[index] = v;
                            }
                            else if (existingMap.TryGetValue(v.Version, out var ev) && ev.JavaMajor is > 0)
                            {
                                updatedFetched[index] = v with { JavaMajor = ev.JavaMajor };
                            }
                            else
                            {
                                // 新增版本：同步取得官方指定的 Java 主要版本
                                int? javaMajor = await MojangVersionCatalog.FetchOfficialJavaMajorAsync(httpPort, v.Url, token).ConfigureAwait(false);
                                updatedFetched[index] = v with { JavaMajor = javaMajor };
                            }
                        }).ConfigureAwait(false);

                    var mergedMap = new Dictionary<string, LoaderVersion>(StringComparer.OrdinalIgnoreCase);
                    foreach (var v in updatedFetched)
                    {
                        mergedMap[v.Version] = v;
                    }
                    foreach (var v in existing)
                    {
                        if (mergedMap.TryGetValue(v.Version, out var current))
                        {
                            if (current.JavaMajor is null && v.JavaMajor is not null)
                            {
                                mergedMap[v.Version] = current with { JavaMajor = v.JavaMajor };
                            }
                        }
                        else
                        {
                            mergedMap.Add(v.Version, v);
                        }
                    }

                    var merged = mergedMap.Values
                        .OrderByDescending(v => VersionValue.ParseOrZero(v.Version))
                        .ToList();

                    MojangVersionCatalog.SaveCachedVersions(cacheFile, [.. merged.Where(IsStableOfficialRelease)]);
                    return FilterMinecraftVersions(merged, includeSnapshots);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "抓取官方 Minecraft 版本清單異常");
        }

        return FilterMinecraftVersions(existing, includeSnapshots);
    }

    [GeneratedRegex("<version>([^<]+)</version>", RegexOptions.CultureInvariant | RegexOptions.IgnoreCase)]
    private static partial Regex MavenVersionPattern();

    private static List<LoaderVersion> ParseMavenMetadataXml(string xmlContent, bool isNeoForge)
    {
        // Maven 版本字串不含實體或 CDATA，直接以 <version> 標籤擷取，免載入 XML 解析器
        var versions = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (Match match in MavenVersionPattern().Matches(xmlContent))
        {
            string raw = match.Groups[1].Value.Trim();
            if (raw.Length > 0 && seen.Add(raw))
            {
                versions.Add(raw);
            }
        }

        var list = new List<LoaderVersion>();
        foreach (string raw in versions)
        {
            if (isNeoForge)
            {
                string? mcVer = MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge(raw);
                bool isStable = !raw.Contains("alpha", StringComparison.OrdinalIgnoreCase)
                             && !raw.Contains("beta", StringComparison.OrdinalIgnoreCase);
                list.Add(new LoaderVersion(raw, Stable: isStable, MinecraftVersion: mcVer));
            }
            else
            {
                int dashIndex = raw.IndexOf('-');
                if (dashIndex > 0)
                {
                    string mcVer = raw[..dashIndex];
                    string loaderVer = raw[(dashIndex + 1)..];
                    if (!ContainsPreReleaseKeyword(loaderVer))
                    {
                        list.Add(new LoaderVersion(loaderVer, Stable: true, MinecraftVersion: mcVer));
                    }
                }
            }
        }

        return list;
    }

    private static readonly System.Buffers.SearchValues<string> PreReleaseKeywords =
        System.Buffers.SearchValues.Create(["alpha", "beta", "snapshot", "rc", "pre", "prerelease"], StringComparison.OrdinalIgnoreCase);

    private static bool ContainsPreReleaseKeyword(string version) =>
        version.AsSpan().ContainsAny(PreReleaseKeywords);

    private static List<LoaderVersion> FilterLoaderByMcVersion(
        IReadOnlyList<LoaderVersion> versions,
        LoaderKind loader,
        string minecraftVersion)
    {
        if (loader is LoaderKind.Fabric or LoaderKind.Quilt)
        {
            if (!MinecraftVersionSemantics.IsFabricCompatible(minecraftVersion))
            {
                return [];
            }

            // Fabric / Quilt: 只保留最新正式版（篩選 stable 且名稱不含預發布關鍵字）
            return [.. versions
                .Where(v => v.Stable && !ContainsPreReleaseKeyword(v.Version))
                .Take(1)];
        }

        if (loader == LoaderKind.Forge)
        {
            // Forge: 從最新版本到舊版本只保留 4 個，篩除含 beta、alpha、snapshot、rc、pre 的預發布版本
            return [.. versions
                .Where(v => string.Equals(v.MinecraftVersion, minecraftVersion, StringComparison.OrdinalIgnoreCase))
                .Where(v => !ContainsPreReleaseKeyword(v.Version))
                .OrderByDescending(VersionSortKey)
                .Take(4)];
        }

        if (loader == LoaderKind.NeoForge)
        {
            if (!MinecraftVersionSemantics.IsNeoForgeCompatible(minecraftVersion))
            {
                return [];
            }

            bool isMc26Plus = VersionValue.TryParse(minecraftVersion, out var val) && val.Major >= 26;
            string prefixedVersion = isMc26Plus ? $"1.{minecraftVersion}" : minecraftVersion;

            // NeoForge: 從最新版本到舊版本只保留 4 個（基本上帶有 beta 字樣故不需要篩選）
            return [.. versions
                .Where(v => string.Equals(v.MinecraftVersion, minecraftVersion, StringComparison.OrdinalIgnoreCase)
                         || (isMc26Plus && string.Equals(v.MinecraftVersion, prefixedVersion, StringComparison.OrdinalIgnoreCase)))
                .OrderByDescending(VersionSortKey)
                .Take(4)];
        }

        return [];
    }

    /// <summary>
    /// 以語意版本排序 Loader 版本（避免字串排序造成 47.9 大於 47.10）
    /// </summary>
    private static VersionValue VersionSortKey(LoaderVersion version) =>
        VersionValue.ParseOrZero(version.Version);

    private static IReadOnlyList<LoaderVersion> FilterMinecraftVersions(
        IReadOnlyList<LoaderVersion> versions,
        bool includeSnapshots) => includeSnapshots
        ? versions
        : [.. versions.Where(static v => v.Stable && MinecraftVersionSemantics.IsOfficialReleaseVersion(v.Version))];

    private bool IsCacheFresh(string cachePath)
    {
        if (!SafeFileSystem.FileExists(cachePath))
        {
            return false;
        }

        var writeTime = SafeFileSystem.GetFileLastWriteTimeUtc(cachePath);
        return DateTime.UtcNow - writeTime < _cacheTtl;
    }

    private static List<LoaderVersion> ParsePaperMinecraftVersions(JsonDocument doc)
    {
        if (!doc.RootElement.TryGetProperty("versions", out var versionsProp) ||
            versionsProp.ValueKind != JsonValueKind.Object)
        {
            return [];
        }

        var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var group in versionsProp.EnumerateObject())
        {
            if (group.Value.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in group.Value.EnumerateArray())
                {
                    string? ver = item.GetString();
                    if (!string.IsNullOrWhiteSpace(ver))
                    {
                        string trimmed = ver.Trim();
                        // 篩選 Version：只保留標準官方正式發布版號（排除 pre, rc, snapshot, experiment 等）
                        if (MinecraftVersionSemantics.IsOfficialReleaseVersion(trimmed))
                        {
                            set.Add(trimmed);
                        }
                    }
                }
            }
        }

        return [.. set
            .OrderByDescending(static v => VersionValue.ParseOrZero(v))
            .Select(static v => new LoaderVersion(v, Stable: true, MinecraftVersion: v))];
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchPaperBuildsAsync(
        string minecraftVersion,
        CancellationToken cancellationToken,
        bool updateCache = true)
    {
        Uri buildsUrl = MojangVersionCatalog.PaperBuildsUri(minecraftVersion);
        var response = await httpPort.GetJsonDocumentAsync(buildsUrl, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccess || response.Payload is null)
        {
            return [];
        }

        using var doc = response.Payload;
        if (doc.RootElement.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        var list = new List<LoaderVersion>();
        foreach (var buildElem in doc.RootElement.EnumerateArray())
        {
            if (!buildElem.TryGetProperty("id", out var idProp) || !idProp.TryGetInt32(out int buildId))
            {
                continue;
            }

            string? channel = buildElem.TryGetProperty("channel", out var cProp) ? cProp.GetString() : null;
            bool isStable = string.Equals(channel, "STABLE", StringComparison.OrdinalIgnoreCase);

            string? downloadUrl = MojangVersionCatalog.TryGetPaperDownload(buildElem, out var download) && download.TryGetProperty("url", out var urlProp)
                ? urlProp.GetString()
                : null;

            list.Add(new LoaderVersion(
                Version: buildId.ToString(System.Globalization.CultureInfo.InvariantCulture),
                Url: downloadUrl,
                Stable: isStable,
                MinecraftVersion: minecraftVersion));
        }

        // PaperMC: 只保留最新正式版（篩選 stable 且排除預發布關鍵字）
        var stableList = list
            .Where(b => b.Stable && !ContainsPreReleaseKeyword(b.Version))
            .OrderByDescending(b => int.TryParse(b.Version, out int id) ? id : 0)
            .ToList();

        if (stableList.Count > 0)
        {
            var latestBuild = stableList[0];
            if (updateCache)
            {
                UpdatePaperVersionLatestBuild(minecraftVersion, latestBuild.Version);
            }
            return [latestBuild];
        }

        if (updateCache)
        {
            RemovePaperVersionIfNoStableBuild(minecraftVersion);
        }
        return [];
    }

    private void RemovePaperVersionIfNoStableBuild(string minecraftVersion)
    {
        try
        {
            string cacheFile = GetPaperCacheFilePath();
            var versions = _memoryPaperMinecraftVersions ?? (SafeFileSystem.FileExists(cacheFile) ? MojangVersionCatalog.LoadCachedVersions(cacheFile) : null);
            if (versions is null || versions.Count == 0)
            {
                return;
            }

            var updated = versions.Where(v => !string.Equals(v.Version, minecraftVersion, StringComparison.OrdinalIgnoreCase)).ToList();
            if (updated.Count != versions.Count)
            {
                _memoryPaperMinecraftVersions = updated;
                MojangVersionCatalog.SaveCachedVersions(cacheFile, updated);
                Logger.Information("Paper 版本 {Version} 因無 STABLE 建置已自快取與清單中剔除", minecraftVersion);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("剔除無 STABLE 建置之 Paper 版本失敗: {Message}", ex.Message);
        }
    }

    private void UpdatePaperVersionLatestBuild(string minecraftVersion, string build)
    {
        try
        {
            string cacheFile = GetPaperCacheFilePath();
            var versions = _memoryPaperMinecraftVersions ?? (SafeFileSystem.FileExists(cacheFile) ? MojangVersionCatalog.LoadCachedVersions(cacheFile) : null);
            if (versions is null || versions.Count == 0)
            {
                return;
            }

            bool changed = false;
            var updated = new List<LoaderVersion>(versions.Count);
            foreach (var v in versions)
            {
                if (string.Equals(v.Version, minecraftVersion, StringComparison.OrdinalIgnoreCase))
                {
                    if (v.Build != build)
                    {
                        updated.Add(v with { Build = build });
                        changed = true;
                    }
                    else
                    {
                        updated.Add(v);
                    }
                }
                else
                {
                    updated.Add(v);
                }
            }

            if (changed)
            {
                _memoryPaperMinecraftVersions = updated;
                MojangVersionCatalog.SaveCachedVersions(cacheFile, updated);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("更新 Paper 快取版本異常: {0}", ex.Message);
        }
    }
}
