using System.Collections.Concurrent;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderCatalogService : ILoaderCatalogService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LoaderCatalogService));
    private static readonly LoaderKind[] ReloadableLoaders = [LoaderKind.Fabric, LoaderKind.Quilt, LoaderKind.Forge, LoaderKind.NeoForge];
    private static readonly TimeSpan CacheTtl = TimeSpan.FromHours(12);

    private readonly IHttpPort _httpPort;
    private readonly string _cacheDir;
    // 記憶體快取皆為帶到期時間的不可變快照；降級（過期快取）結果不寫入，下次仍重試遠端
    private readonly ConcurrentDictionary<(LoaderKind, string), MemoryEntry> _memoryLoaderCache = new();
    private volatile MemoryEntry? _memoryMinecraftVersions;
    private volatile MemoryEntry? _memoryPaperMinecraftVersions;
    private readonly SingleFlight<(LoaderKind, string), IReadOnlyList<LoaderVersion>> _loaderVersionsSingleFlight = new();
    private readonly SingleFlight<LoaderKind, IReadOnlyList<LoaderVersion>> _loaderCatalogSingleFlight = new();
    private readonly TimeProvider _timeProvider;

    public LoaderCatalogService(IHttpPort httpPort, string cacheDirectory, TimeProvider timeProvider)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        ArgumentNullException.ThrowIfNull(timeProvider);
        _timeProvider = timeProvider;
        ArgumentException.ThrowIfNullOrWhiteSpace(cacheDirectory);
        _httpPort = httpPort;
        _cacheDir = SafeFileSystem.ResolveStableDirectory(cacheDirectory, create: true);
    }

    private string GetMinecraftCacheFilePath() => MojangVersionCatalog.GetVersionsCachePath(_cacheDir);
    private string GetPaperCacheFilePath() => MojangVersionCatalog.GetPaperVersionsCachePath(_cacheDir);
    private string GetLoaderCacheFilePath(LoaderKind loader) => Path.Combine(_cacheDir, $"{loader.ToString().ToLowerInvariant()}_versions_cache.json");

    private sealed record MemoryEntry(IReadOnlyList<LoaderVersion> Versions, DateTimeOffset ExpiresAtUtc);

    private MemoryEntry CreateMemoryEntry(IEnumerable<LoaderVersion> versions) =>
        new([.. versions], _timeProvider.GetUtcNow() + CacheTtl);

    private bool TryGetFresh(MemoryEntry? entry, out IReadOnlyList<LoaderVersion> versions)
    {
        if (entry is not null && entry.Versions.Count > 0 && _timeProvider.GetUtcNow() < entry.ExpiresAtUtc)
        {
            versions = entry.Versions;
            return true;
        }

        versions = [];
        return false;
    }

    internal async Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!includeSnapshots && TryGetFresh(_memoryMinecraftVersions, out var memoryVersions))
        {
            return memoryVersions;
        }

        string cacheFile = GetMinecraftCacheFilePath();

        if (!includeSnapshots && IsCacheFresh(cacheFile))
        {
            var validCached = LoadValidatedCache(cacheFile, IsStableOfficialRelease);
            if (validCached.Count > 0)
            {
                var filtered = FilterMinecraftVersions(validCached, includeSnapshots: false);
                _memoryMinecraftVersions = CreateMemoryEntry(filtered);
                return filtered;
            }
        }

        var parsed = await MojangVersionCatalog.FetchManifestAsync(_httpPort, cancellationToken).ConfigureAwait(false);
        if (parsed is { Count: > 0 })
        {
            // 寫回時保留快取既有的 JavaMajor，避免每次重抓清單都需重新查詢
            List<LoaderVersion> withJavaMajor = parsed;
            MojangVersionCatalog.UpdateCachedVersions(cacheFile, current =>
            {
                var knownJavaMajors = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                foreach (var cached in current)
                {
                    if (cached.JavaMajor is > 0 and int javaMajor)
                    {
                        knownJavaMajors[cached.Version] = javaMajor;
                    }
                }

                withJavaMajor = [.. parsed.Select(v => v.JavaMajor is null && knownJavaMajors.TryGetValue(v.Version, out int major)
                    ? v with { JavaMajor = major }
                    : v)];
                return [.. withJavaMajor.Where(IsStableOfficialRelease)];
            });

            var stable = FilterMinecraftVersions(withJavaMajor, includeSnapshots: false);
            _memoryMinecraftVersions = CreateMemoryEntry(stable);
            return includeSnapshots ? withJavaMajor : stable;
        }

        // 遠端失敗時嘗試過期快取；降級結果不寫入記憶體快取
        Logger.Warning("抓取 Mojang 版本清單失敗，改用過期快取");
        var validStale = LoadValidatedCache(cacheFile, IsStableOfficialRelease);
        return validStale.Count == 0 ? [] : FilterMinecraftVersions(validStale, includeSnapshots);
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

    private async Task<int?> GetOfficialJavaMajorAsync(
        Dictionary<string, LoaderVersion> official,
        string minecraftVersion,
        CancellationToken cancellationToken)
    {
        if (!official.TryGetValue(minecraftVersion, out var version))
        {
            return null;
        }

        return version.JavaMajor is > 0
            ? version.JavaMajor
            : string.IsNullOrWhiteSpace(version.Url)
                ? null
                : await MojangVersionCatalog.FetchOfficialJavaMajorAsync(_httpPort, version.Url, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>讀取快取並剔除無效項目；有剔除時回寫</summary>
    private static List<LoaderVersion> LoadValidatedCache(string cacheFile, Func<LoaderVersion, bool> isValid)
    {
        var cached = MojangVersionCatalog.LoadCachedVersions(cacheFile);
        var valid = cached.Where(isValid).ToList();
        if (valid.Count > 0 && valid.Count != cached.Count)
        {
            MojangVersionCatalog.SaveCachedVersions(cacheFile, valid);
        }

        return valid;
    }

    public async Task<IReadOnlyList<LoaderVersion>> GetLoaderVersionsAsync(
        LoaderKind loader,
        string minecraftVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(minecraftVersion);
        cancellationToken.ThrowIfCancellationRequested();

        var memoryKey = (loader, minecraftVersion);
        if (_memoryLoaderCache.TryGetValue(memoryKey, out var memoryEntry) && TryGetFresh(memoryEntry, out var memoryVersions))
        {
            return memoryVersions;
        }

        if (loader == LoaderKind.Paper)
        {
            string paperCache = GetPaperCacheFilePath();
            if (IsCacheFresh(paperCache))
            {
                var cachedPaper = MojangVersionCatalog.LoadCachedVersions(paperCache);
                var match = cachedPaper.FirstOrDefault(v => string.Equals(v.Version, minecraftVersion, StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(v.Build));
                if (match is not null)
                {
                    List<LoaderVersion> builds = [new LoaderVersion(match.Build!, Stable: true, MinecraftVersion: minecraftVersion)];
                    _memoryLoaderCache[memoryKey] = CreateMemoryEntry(builds);
                    return builds;
                }
            }

            return await _loaderVersionsSingleFlight.WaitAsync(memoryKey, async _ =>
            {
                try
                {
                    var fetched = await FetchPaperBuildsAsync(minecraftVersion, CancellationToken.None).ConfigureAwait(false);
                    if (fetched.Count > 0)
                    {
                        _memoryLoaderCache[memoryKey] = CreateMemoryEntry(fetched);
                        return fetched;
                    }
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Warning(ex, "取得 Paper 組建版本清單失敗");
                }

                return [];
            }, cancellationToken).ConfigureAwait(false);
        }

        string cacheFile = GetLoaderCacheFilePath(loader);

        if (TryGetFreshLoaderCache(cacheFile, loader, minecraftVersion, memoryKey) is { } cachedResult)
        {
            return cachedResult;
        }

        return await _loaderVersionsSingleFlight.WaitAsync(memoryKey, async _ =>
        {
            if (TryGetFreshLoaderCache(cacheFile, loader, minecraftVersion, memoryKey) is { } cachedResult)
            {
                return cachedResult;
            }

            try
            {
                IReadOnlyList<LoaderVersion> fetched = await _loaderCatalogSingleFlight.WaitAsync(loader, l => FetchLoaderVersionsAsync(l, CancellationToken.None), CancellationToken.None).ConfigureAwait(false);

                if (fetched.Count > 0)
                {
                    var pruned = PruneVersionsForCache(loader, fetched);
                    MojangVersionCatalog.SaveCachedVersions(cacheFile, pruned);
                    var filtered = FilterLoaderByMcVersion(pruned, loader, minecraftVersion);
                    if (filtered.Count > 0)
                    {
                        _memoryLoaderCache[memoryKey] = CreateMemoryEntry(filtered);
                    }

                    return filtered;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "抓取載入器版本清單時發生例外");
            }

            // 失敗結果與例外一律改用過期快取；不寫入記憶體快取，下次呼叫仍會重試遠端
            Logger.Warning("抓取 {Loader} 版本清單失敗，改用過期快取", loader);
            return FilterLoaderByMcVersion(MojangVersionCatalog.LoadCachedVersions(cacheFile), loader, minecraftVersion);
        }, cancellationToken).ConfigureAwait(false);
    }

    private List<LoaderVersion>? TryGetFreshLoaderCache(
        string cacheFile,
        LoaderKind loader,
        string minecraftVersion,
        (LoaderKind, string) memoryKey)
    {
        if (!IsCacheFresh(cacheFile))
        {
            return null;
        }

        // 新鮮快取即為完整清單；篩選結果為空代表此版本無對應載入器，不重抓全量 metadata
        var cached = MojangVersionCatalog.LoadCachedVersions(cacheFile);
        if (cached.Count == 0)
        {
            return null;
        }

        var filtered = FilterLoaderByMcVersion(cached, loader, minecraftVersion);
        if (filtered.Count > 0)
        {
            _memoryLoaderCache[memoryKey] = CreateMemoryEntry(filtered);
        }

        return filtered;
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

    /// <summary>僅保留有官方伺服器 jar 的穩定版本（供快取寫入與讀取時共用）</summary>
    private static bool IsStableOfficialRelease(LoaderVersion version) =>
        version.Stable && MojangVersionCatalog.HasOfficialServerJar(version.Version);

    public async Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.WhenAll(ReloadableLoaders.Select(loader => ReloadLoaderAsync(loader, cancellationToken))).ConfigureAwait(false);

        // 檔案快取已更新；清除記憶體快取，後續查詢才會讀到新資料
        _memoryLoaderCache.Clear();
    }

    private void ClearLoaderMemory(Func<LoaderKind, bool> predicate)
    {
        foreach (var key in _memoryLoaderCache.Keys)
        {
            if (predicate(key.Item1))
            {
                _memoryLoaderCache.TryRemove(key, out _);
            }
        }
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
            ClearLoaderMemory(staleLoaders.Contains);
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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "重新載入 {Loader} 版本清單失敗", loader);
        }
    }

    private async Task<IReadOnlyList<LoaderVersion>> ReloadAndMergeMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        string cacheFile = GetMinecraftCacheFilePath();
        var existing = SafeFileSystem.FileExists(cacheFile) ? MojangVersionCatalog.LoadCachedVersions(cacheFile) : [];

        try
        {
            var fetched = await MojangVersionCatalog.FetchManifestAsync(_httpPort, cancellationToken).ConfigureAwait(false);
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
                                int? javaMajor = await MojangVersionCatalog.FetchOfficialJavaMajorAsync(_httpPort, v.Url, token).ConfigureAwait(false);
                                updatedFetched[index] = v with { JavaMajor = javaMajor };
                            }
                        }).ConfigureAwait(false);

                    // 抓取期間快取可能已更新，以寫回當下的最新快取合併
                    List<LoaderVersion> merged = [];
                    MojangVersionCatalog.UpdateCachedVersions(cacheFile, latest =>
                    {
                        var mergedMap = new Dictionary<string, LoaderVersion>(StringComparer.OrdinalIgnoreCase);
                        foreach (var v in updatedFetched)
                        {
                            mergedMap[v.Version] = v;
                        }
                        foreach (var v in latest)
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

                        merged = [.. mergedMap.Values.OrderByDescending(static v => VersionValue.ParseOrZero(v.Version))];
                        return [.. merged.Where(IsStableOfficialRelease)];
                    });

                    var stable = FilterMinecraftVersions(merged, includeSnapshots: false);
                    _memoryMinecraftVersions = CreateMemoryEntry(stable);
                    return includeSnapshots ? merged : stable;
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "抓取官方 Minecraft 版本清單失敗");
        }

        return FilterMinecraftVersions(existing, includeSnapshots);
    }

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
        return _timeProvider.GetUtcNow().UtcDateTime - writeTime < CacheTtl;
    }
}
