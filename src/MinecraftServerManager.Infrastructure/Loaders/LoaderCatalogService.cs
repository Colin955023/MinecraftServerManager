using System.Text.Json;
using System.Xml;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;
using MinecraftServerManager.Core.Utilities;
using System.Collections.Concurrent;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed class LoaderCatalogService(IHttpPort httpPort, string cacheDirectory) : ILoaderCatalogService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("LoaderCatalogService");
    private static readonly LoaderKind[] ReloadableLoaders = [LoaderKind.Fabric, LoaderKind.Quilt, LoaderKind.Forge, LoaderKind.NeoForge];
    private readonly string _cacheDir = InitializeCacheDirectory(cacheDirectory);
    private readonly TimeSpan _cacheTtl = TimeSpan.FromHours(12);
    private readonly ConcurrentDictionary<(LoaderKind, string), IReadOnlyList<LoaderVersion>> _memoryLoaderCache = new();
    private IReadOnlyList<LoaderVersion>? _memoryMinecraftVersions;
    private IReadOnlyList<LoaderVersion>? _memoryPaperMinecraftVersions;

    private static string InitializeCacheDirectory(string cacheDirectory)
    {
        string dir = SafeFileSystem.ResolveStableDirectory(cacheDirectory, create: true);
        try
        {
            if (Directory.Exists(dir))
            {
                foreach (string file in Directory.EnumerateFiles(dir, "paper_*_builds_cache.json"))
                {
                    try
                    {
                        File.Delete(file);
                    }
                    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                    {
                        Logger.Warning("清理舊版 Paper builds 快取檔案失敗: {Path}, 原因: {Message}", file, ex.Message);
                    }
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning("列舉快取目錄檔案失敗: {Message}", ex.Message);
        }
        return dir;
    }

    public async Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!includeSnapshots && _memoryMinecraftVersions is { Count: > 0 })
        {
            return _memoryMinecraftVersions;
        }

        string cacheFile = Path.Combine(_cacheDir, "mc_versions_cache.json");

        if (!includeSnapshots && IsCacheFresh(cacheFile))
        {
            var cached = LoadCachedVersions(cacheFile);
            var validCached = cached.Where(v => v.Stable && HasOfficialServerJar(v.Version)).ToList();
            if (validCached.Count > 0)
            {
                if (validCached.Count != cached.Count)
                {
                    SaveCachedVersions(cacheFile, validCached);
                }
                var filtered = FilterMinecraftVersions(validCached, includeSnapshots: false);
                _memoryMinecraftVersions = filtered;
                return filtered;
            }
        }

        try
        {
            string manifestUrl = "https://piston-meta.mojang.com/mc/game/version_manifest.json";
            var response = await httpPort.GetJsonDocumentAsync(new Uri(manifestUrl), cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccess || response.Payload is null)
            {
                return [];
            }

            List<LoaderVersion> parsed;
            using (response.Payload)
            {
                parsed = ParseMinecraftManifest(response.Payload);
            }

            if (parsed.Count > 0)
            {
                var cacheable = parsed.Where(v => v.Stable && HasOfficialServerJar(v.Version)).ToList();
                SaveCachedVersions(cacheFile, cacheable);
                var filtered = FilterMinecraftVersions(parsed, includeSnapshots);
                if (!includeSnapshots)
                {
                    _memoryMinecraftVersions = filtered;
                }
                return filtered;
            }
        }
        catch
        {
            // 遠端失敗時嘗試過期快取
            if (File.Exists(cacheFile))
            {
                var stale = LoadCachedVersions(cacheFile);
                var validStale = stale.Where(v => v.Stable && HasOfficialServerJar(v.Version)).ToList();
                if (validStale.Count > 0)
                {
                    if (validStale.Count != stale.Count)
                    {
                        SaveCachedVersions(cacheFile, validStale);
                    }
                    var filtered = FilterMinecraftVersions(validStale, includeSnapshots);
                    if (!includeSnapshots)
                    {
                        _memoryMinecraftVersions = filtered;
                    }
                    return filtered;
                }
            }
        }

        return [];
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

        string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");

        if (!forceReload && IsCacheFresh(cacheFile))
        {
            var cached = LoadCachedVersions(cacheFile);
            var validCached = cached.Where(v => !string.IsNullOrWhiteSpace(v.Build) && v.JavaMajor is > 0).ToList();
            if (validCached.Count > 0)
            {
                if (validCached.Count != cached.Count)
                {
                    SaveCachedVersions(cacheFile, validCached);
                }
                _memoryPaperMinecraftVersions = validCached;
                return validCached;
            }
        }

        try
        {
            string url = "https://fill.papermc.io/v3/projects/paper";
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
                    // 載入既有快取以進行差異比對（已具備 JavaMajor 與有效 Build 的版本無須重複呼叫 API）
                    var existingMap = new Dictionary<string, (int JavaMajor, string Build)>(StringComparer.OrdinalIgnoreCase);
                    if (File.Exists(cacheFile))
                    {
                        foreach (var ev in LoadCachedVersions(cacheFile))
                        {
                            if (ev.JavaMajor is > 0 && !string.IsNullOrWhiteSpace(ev.Build))
                            {
                                existingMap[ev.Version] = (ev.JavaMajor.Value, ev.Build);
                            }
                        }
                    }

                    using var throttler = new SemaphoreSlim(5, 5);
                    var fullVersions = await Task.WhenAll(baseVersions.Select(async v =>
                    {
                        if (existingMap.TryGetValue(v.Version, out var existing))
                        {
                            return v with { JavaMajor = existing.JavaMajor, Build = existing.Build };
                        }

                        await throttler.WaitAsync(cancellationToken).ConfigureAwait(false);
                        try
                        {
                            // 查詢 STABLE 建置清單；若無任何 STABLE 建置，直接剔除（不納入快取）
                            var builds = await FetchPaperBuildsAsync(v.Version, cancellationToken, updateCache: false).ConfigureAwait(false);
                            if (builds.Count == 0 || string.IsNullOrWhiteSpace(builds[0].Version))
                            {
                                return null;
                            }

                            string latestBuild = builds[0].Version;
                            int? javaMajor = await FetchPaperVersionJavaMajorAsync(v.Version, cancellationToken).ConfigureAwait(false);
                            return v with { JavaMajor = javaMajor, Build = latestBuild };
                        }
                        finally
                        {
                            throttler.Release();
                        }
                    })).ConfigureAwait(false);

                    var result = fullVersions
                        .Where(v => v is not null)
                        .Select(v => v!)
                        .OrderByDescending(v => VersionValue.TryParse(v.Version, out var val) ? val : VersionValue.Zero)
                        .ToList();

                    SaveCachedVersions(cacheFile, result);
                    _memoryPaperMinecraftVersions = result;
                    return result;
                }
            }
        }
        catch
        {
            if (File.Exists(cacheFile))
            {
                var stale = LoadCachedVersions(cacheFile);
                var validStale = stale.Where(v => !string.IsNullOrWhiteSpace(v.Build) && v.JavaMajor is > 0).ToList();
                if (validStale.Count > 0)
                {
                    return validStale;
                }
            }
        }

        return [];
    }

    private async Task<int?> FetchPaperVersionJavaMajorAsync(string version, CancellationToken cancellationToken)
    {
        try
        {
            string url = $"https://fill.papermc.io/v3/projects/paper/versions/{version}";
            string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                return null;
            }

            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("version", out var vProp) &&
                vProp.TryGetProperty("java", out var jProp) &&
                jProp.TryGetProperty("version", out var jvProp) &&
                jvProp.TryGetProperty("minimum", out var minProp) &&
                minProp.TryGetInt32(out int minimum))
            {
                // Minecraft 伺服器最低執行環境為 Java 8（jre-legacy）
                return Math.Max(8, minimum);
            }
        }
        catch
        {
        }

        return null;
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
            catch
            {
            }

            return [];
        }

        if (_memoryLoaderCache.TryGetValue((loader, minecraftVersion), out var memCached))
        {
            return memCached;
        }

        string cacheFile = Path.Combine(_cacheDir, $"{loader.ToString().ToLowerInvariant()}_versions_cache.json");

        if (IsCacheFresh(cacheFile))
        {
            var cached = LoadCachedVersions(cacheFile);
            var filtered = FilterLoaderByMcVersion(cached, loader, minecraftVersion);
            if (filtered.Count > 0)
            {
                _memoryLoaderCache[(loader, minecraftVersion)] = filtered;
                return filtered;
            }
        }

        try
        {
            IReadOnlyList<LoaderVersion> fetched = loader switch
            {
                LoaderKind.Fabric => await FetchFabricVersionsAsync(cancellationToken).ConfigureAwait(false),
                LoaderKind.Quilt => await FetchQuiltVersionsAsync(cancellationToken).ConfigureAwait(false),
                LoaderKind.Forge => await FetchForgeVersionsAsync(cancellationToken).ConfigureAwait(false),
                LoaderKind.NeoForge => await FetchNeoForgeVersionsAsync(cancellationToken).ConfigureAwait(false),
                _ => []
            };

            if (fetched.Count > 0)
            {
                var pruned = PruneVersionsForCache(loader, fetched);
                SaveCachedVersions(cacheFile, pruned);
                var filtered = FilterLoaderByMcVersion(pruned, loader, minecraftVersion);
                _memoryLoaderCache[(loader, minecraftVersion)] = filtered;
                return filtered;
            }
        }
        catch
        {
            if (File.Exists(cacheFile))
            {
                var stale = LoadCachedVersions(cacheFile);
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
                .SelectMany(static g => g.OrderByDescending(static v => v.Version, StringComparer.OrdinalIgnoreCase).Take(4))];
        }

        return versions;
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchFabricVersionsAsync(CancellationToken cancellationToken)
    {
        string url = "https://meta.fabricmc.net/v2/versions/loader";
        string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(json))
        {
            return [];
        }

        using var doc = JsonDocument.Parse(json);
        var list = new List<LoaderVersion>();
        foreach (var element in doc.RootElement.EnumerateArray())
        {
            if (element.TryGetProperty("version", out var vProp))
            {
                string? ver = vProp.GetString();
                if (string.IsNullOrWhiteSpace(ver) || ContainsPreReleaseKeyword(ver))
                {
                    continue;
                }

                bool stable = (element.TryGetProperty("stable", out var sProp) && sProp.GetBoolean()) || !ContainsPreReleaseKeyword(ver);
                list.Add(new LoaderVersion(ver, Stable: stable));
            }
        }

        return list;
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchQuiltVersionsAsync(CancellationToken cancellationToken)
    {
        string url = "https://meta.quiltmc.org/v3/versions/loader";
        string? json = await httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(json))
        {
            return [];
        }

        using var doc = JsonDocument.Parse(json);
        var list = new List<LoaderVersion>();
        foreach (var element in doc.RootElement.EnumerateArray())
        {
            if (element.TryGetProperty("version", out var vProp))
            {
                string? ver = vProp.GetString();
                if (string.IsNullOrWhiteSpace(ver) || ContainsPreReleaseKeyword(ver))
                {
                    continue;
                }

                bool stable = (element.TryGetProperty("stable", out var sProp) && sProp.GetBoolean()) || !ContainsPreReleaseKeyword(ver);
                list.Add(new LoaderVersion(ver, Stable: stable));
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

    public async Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.WhenAll(ReloadableLoaders.Select(loader => ReloadLoaderAsync(loader, cancellationToken))).ConfigureAwait(false);
    }

    public async Task WarmupLoadersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var staleLoaders = ReloadableLoaders
            .Where(loader => !IsCacheFresh(Path.Combine(_cacheDir, $"{loader.ToString().ToLowerInvariant()}_versions_cache.json")))
            .ToList();

        if (staleLoaders.Count > 0)
        {
            await Task.WhenAll(staleLoaders.Select(loader => ReloadLoaderAsync(loader, cancellationToken))).ConfigureAwait(false);
        }
    }

    private async Task ReloadLoaderAsync(LoaderKind loader, CancellationToken cancellationToken)
    {
        string cacheFile = Path.Combine(_cacheDir, $"{loader.ToString().ToLowerInvariant()}_versions_cache.json");
        try
        {
            IReadOnlyList<LoaderVersion> fetched = loader switch
            {
                LoaderKind.Fabric => await FetchFabricVersionsAsync(cancellationToken).ConfigureAwait(false),
                LoaderKind.Quilt => await FetchQuiltVersionsAsync(cancellationToken).ConfigureAwait(false),
                LoaderKind.Forge => await FetchForgeVersionsAsync(cancellationToken).ConfigureAwait(false),
                LoaderKind.NeoForge => await FetchNeoForgeVersionsAsync(cancellationToken).ConfigureAwait(false),
                _ => []
            };
            if (fetched.Count > 0)
            {
                SaveCachedVersions(cacheFile, PruneVersionsForCache(loader, fetched));
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
        string cacheFile = Path.Combine(_cacheDir, "mc_versions_cache.json");
        var existing = File.Exists(cacheFile) ? LoadCachedVersions(cacheFile) : [];

        try
        {
            string manifestUrl = "https://piston-meta.mojang.com/mc/game/version_manifest.json";
            var response = await httpPort.GetJsonDocumentAsync(new Uri(manifestUrl), cancellationToken).ConfigureAwait(false);
            if (response.IsSuccess && response.Payload is not null)
            {
                List<LoaderVersion> fetched;
                using (response.Payload)
                {
                    fetched = ParseMinecraftManifest(response.Payload);
                }
                if (fetched.Count > 0)
                {
                    var existingMap = new Dictionary<string, LoaderVersion>(StringComparer.OrdinalIgnoreCase);
                    foreach (var v in existing)
                    {
                        existingMap[v.Version] = v;
                    }

                    using var throttler = new SemaphoreSlim(5, 5);
                    var updatedFetched = await Task.WhenAll(fetched.Select(async v =>
                    {
                        if (!v.Stable || !MinecraftVersionSemantics.IsOfficialReleaseVersion(v.Version) || string.IsNullOrWhiteSpace(v.Url))
                        {
                            return v;
                        }

                        if (existingMap.TryGetValue(v.Version, out var ev) && ev.JavaMajor is > 0)
                        {
                            return v with { JavaMajor = ev.JavaMajor };
                        }

                        // 新增版本：同步取得官方指定的 Java 主要版本
                        await throttler.WaitAsync(cancellationToken).ConfigureAwait(false);
                        try
                        {
                            int? javaMajor = await FetchOfficialVersionJavaMajorAsync(v.Url, cancellationToken).ConfigureAwait(false);
                            return v with { JavaMajor = javaMajor };
                        }
                        finally
                        {
                            throttler.Release();
                        }
                    })).ConfigureAwait(false);

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
                        .OrderByDescending(v => VersionValue.TryParse(v.Version, out var val) ? val : VersionValue.Zero)
                        .ToList();

                    SaveCachedVersions(cacheFile, [.. merged.Where(v => v.Stable && HasOfficialServerJar(v.Version))]);
                    return FilterMinecraftVersions(merged, includeSnapshots);
                }
            }
        }
        catch
        {
        }

        return FilterMinecraftVersions(existing, includeSnapshots);
    }

    private static List<LoaderVersion> ParseMavenMetadataXml(string xmlContent, bool isNeoForge)
    {
        var versions = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        using var stringReader = new StringReader(xmlContent);
        var settings = new XmlReaderSettings
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            IgnoreWhitespace = true,
            IgnoreComments = true,
        };
        using var reader = XmlReader.Create(stringReader, settings);
        string? currentElement = null;
        while (reader.Read())
        {
            switch (reader.NodeType)
            {
                case XmlNodeType.Element:
                    currentElement = reader.Name;
                    break;
                case XmlNodeType.Text or XmlNodeType.CDATA:
                    if (string.Equals(currentElement, "version", StringComparison.OrdinalIgnoreCase))
                    {
                        string raw = reader.Value.Trim();
                        if (!string.IsNullOrEmpty(raw) && seen.Add(raw))
                        {
                            versions.Add(raw);
                        }
                    }
                    break;
                case XmlNodeType.EndElement:
                    if (string.Equals(reader.Name, "version", StringComparison.OrdinalIgnoreCase))
                    {
                        currentElement = null;
                    }
                    break;
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

    private static readonly string[] PreReleaseKeywords = ["alpha", "beta", "snapshot", "rc", "pre", "prerelease"];

    private static bool ContainsPreReleaseKeyword(string version)
    {
        foreach (string keyword in PreReleaseKeywords)
        {
            if (version.Contains(keyword, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

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
                .OrderByDescending(v => v.Version, StringComparer.OrdinalIgnoreCase)
                .Take(4)];
        }

        if (loader == LoaderKind.NeoForge)
        {
            if (!MinecraftVersionSemantics.IsNeoForgeCompatible(minecraftVersion))
            {
                return [];
            }

            bool isMc26Plus = minecraftVersion.StartsWith("26.", StringComparison.OrdinalIgnoreCase) ||
                              (VersionValue.TryParse(minecraftVersion, out var val) && val.Major >= 26);
            string prefixedVersion = isMc26Plus ? $"1.{minecraftVersion}" : minecraftVersion;

            // NeoForge: 從最新版本到舊版本只保留 4 個（基本上帶有 beta 字樣故不需要篩選）
            return [.. versions
                .Where(v => string.Equals(v.MinecraftVersion, minecraftVersion, StringComparison.OrdinalIgnoreCase)
                         || (isMc26Plus && string.Equals(v.MinecraftVersion, prefixedVersion, StringComparison.OrdinalIgnoreCase)))
                .OrderByDescending(v => v.Version, StringComparer.OrdinalIgnoreCase)
                .Take(4)];
        }

        return [];
    }

    private static bool HasOfficialServerJar(string versionId)
    {
        if (VersionValue.TryParse(versionId, out var v))
        {
            // 官方 server jar 自 1.2.5 起提供下載
            if (v.Major > 1)
            {
                return true;
            }

            if (v.Major == 1)
            {
                if (v.Minor > 2)
                {
                    return true;
                }

                if (v.Minor == 2 && v.Patch >= 5)
                {
                    return true;
                }
            }
        }
        return false;
    }

    internal static List<LoaderVersion> ParseMinecraftManifest(string json)
    {
        using var doc = JsonDocument.Parse(json);
        return ParseMinecraftManifest(doc);
    }

    private static List<LoaderVersion> ParseMinecraftManifest(JsonDocument doc)
    {
        if (!doc.RootElement.TryGetProperty("versions", out var versionsElem))
        {
            return [];
        }

        var list = new List<LoaderVersion>();
        foreach (var elem in versionsElem.EnumerateArray())
        {
            string? id = elem.GetProperty("id").GetString();
            string? type = elem.GetProperty("type").GetString();
            string? url = elem.TryGetProperty("url", out var u) ? u.GetString() : null;

            if (!string.IsNullOrEmpty(id))
            {
                bool isRelease = string.Equals(type, "release", StringComparison.OrdinalIgnoreCase);
                if (isRelease)
                {
                    if (HasOfficialServerJar(id))
                    {
                        list.Add(new LoaderVersion(id, Url: url, Stable: true));
                    }
                }
                else
                {
                    list.Add(new LoaderVersion(id, Url: url, Stable: false));
                }
            }
        }

        return [.. list.OrderByDescending(static v => VersionValue.TryParse(v.Version, out var val) ? val : VersionValue.Zero)];
    }

    private static IReadOnlyList<LoaderVersion> FilterMinecraftVersions(
        IReadOnlyList<LoaderVersion> versions,
        bool includeSnapshots) => includeSnapshots
        ? versions
        : [.. versions.Where(static v => v.Stable && MinecraftVersionSemantics.IsOfficialReleaseVersion(v.Version))];

    private bool IsCacheFresh(string cachePath)
    {
        if (!File.Exists(cachePath))
        {
            return false;
        }

        var writeTime = File.GetLastWriteTimeUtc(cachePath);
        return DateTime.UtcNow - writeTime < _cacheTtl;
    }

    private static List<LoaderVersion> LoadCachedVersions(string cachePath)
    {
        try
        {
            string json = File.ReadAllText(cachePath);
            return JsonCodec.Deserialize<List<LoaderVersion>>(json) ?? [];
        }
        catch
        {
            return [];
        }
    }

    private static void SaveCachedVersions(string cachePath, IReadOnlyList<LoaderVersion> versions)
    {
        try
        {
            AtomicFileWriter.WriteJson(cachePath, versions, indented: true);
        }
        catch (Exception ex)
        {
            Logger.Warning("寫入版本快取失敗: {Path}, 原因: {Message}", cachePath, ex.Message);
        }
    }

    internal static List<LoaderVersion> ParsePaperMinecraftVersions(string json)
    {
        using var doc = JsonDocument.Parse(json);
        return ParsePaperMinecraftVersions(doc);
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
            .OrderByDescending(static v => VersionValue.TryParse(v, out var val) ? val : VersionValue.Zero)
            .Select(static v => new LoaderVersion(v, Stable: true, MinecraftVersion: v))];
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchPaperBuildsAsync(
        string minecraftVersion,
        CancellationToken cancellationToken,
        bool updateCache = true)
    {
        string buildsUrl = $"https://fill.papermc.io/v3/projects/paper/versions/{minecraftVersion}/builds";
        var response = await httpPort.GetJsonDocumentAsync(new Uri(buildsUrl), cancellationToken).ConfigureAwait(false);
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

            string? downloadUrl = null;
            if (buildElem.TryGetProperty("downloads", out var downloadsProp) && downloadsProp.ValueKind == JsonValueKind.Object)
            {
                if (downloadsProp.TryGetProperty("server:application", out var appProp) &&
                    appProp.TryGetProperty("url", out var urlProp))
                {
                    downloadUrl = urlProp.GetString();
                }
                else
                {
                    foreach (var prop in downloadsProp.EnumerateObject())
                    {
                        if (prop.Value.TryGetProperty("url", out var fallbackUrlProp))
                        {
                            downloadUrl = fallbackUrlProp.GetString();
                            break;
                        }
                    }
                }
            }

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
            string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");
            var versions = _memoryPaperMinecraftVersions ?? (File.Exists(cacheFile) ? LoadCachedVersions(cacheFile) : null);
            if (versions is null || versions.Count == 0)
            {
                return;
            }

            var updated = versions.Where(v => !string.Equals(v.Version, minecraftVersion, StringComparison.OrdinalIgnoreCase)).ToList();
            if (updated.Count != versions.Count)
            {
                _memoryPaperMinecraftVersions = updated;
                SaveCachedVersions(cacheFile, updated);
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
            string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");
            var versions = _memoryPaperMinecraftVersions ?? (File.Exists(cacheFile) ? LoadCachedVersions(cacheFile) : null);
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
                SaveCachedVersions(cacheFile, updated);
            }
        }
        catch
        {
        }
    }

    private async Task<int?> FetchOfficialVersionJavaMajorAsync(string url, CancellationToken cancellationToken)
    {
        try
        {
            var response = await httpPort.GetJsonDocumentAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccess || response.Payload is null)
            {
                return null;
            }

            using (response.Payload)
            {
                return MinecraftJavaRequirementService.ParseJavaMajorFromVersionJson(response.Payload.RootElement);
            }
        }
        catch
        {
            return null;
        }
    }
}
