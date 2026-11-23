using System.Collections.Concurrent;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

/// <summary>依 Mojang 官方 version package 取得並快取 Java major 需求，不以版本號推算</summary>
public sealed class MinecraftJavaRequirementService : IMinecraftJavaRequirementService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MinecraftJavaRequirementService));

    private readonly IHttpPort _httpPort;
    private readonly string _cacheDirectory;

    /// <summary>重新載入時整份替換，讀取端永遠看到一致的快照</summary>
    private volatile ConcurrentDictionary<string, int> _memoryCache = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>同一快取鍵的並發查詢共用同一個遠端請求</summary>
    private readonly SingleFlight<string, int> _inFlight = new(StringComparer.OrdinalIgnoreCase);
    private readonly Lock _lock = new();
    private volatile bool _cacheLoaded;

    public MinecraftJavaRequirementService(IHttpPort httpPort, string cacheDirectory)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        ArgumentException.ThrowIfNullOrWhiteSpace(cacheDirectory);
        _httpPort = httpPort;
        _cacheDirectory = SafeFileSystem.ResolveStableDirectory(cacheDirectory, create: true);
    }

    public async Task<int> GetRequiredJavaMajorAsync(
        string minecraftVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(minecraftVersion);

        // Java major 僅依 Mojang 官方 JSON
        string cleaned = minecraftVersion.Trim();
        EnsureCacheLoaded();

        if (_memoryCache.TryGetValue(cleaned, out int cachedMajor) && cachedMajor > 0)
        {
            return cachedMajor;
        }

        // 遠端請求不繫結個別呼叫端的取消權杖，呼叫端取消只停止等待
        return await _inFlight.WaitAsync(cleaned, FetchAndCacheAsync, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>自官方來源抓取並寫入快取；失敗時擲出，進行中記錄由 <see cref="SingleFlight{TKey, TValue}"/> 移除</summary>
    private async Task<int> FetchAndCacheAsync(string cleaned)
    {
        // 快取未命中：自官方 Manifest 與版本 Package JSON 動態抓取
        int? remoteMajor = await FetchJavaMajorFromOfficialAsync(cleaned, CancellationToken.None).ConfigureAwait(false);
        if (remoteMajor is > 0)
        {
            _memoryCache[cleaned] = remoteMajor.Value;
            PersistCache();
            return remoteMajor.Value;
        }

        throw new InvalidOperationException($"無法從 Mojang 官方或載入器版本資訊取得 Minecraft 版本「{cleaned}」指定的 Java major 版本。");
    }

    public int? GetCachedJavaMajor(string minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return null;
        }

        EnsureCacheLoaded();
        return _memoryCache.TryGetValue(minecraftVersion.Trim(), out int cachedMajor) && cachedMajor > 0
            ? cachedMajor
            : null;
    }

    public IReadOnlyList<int> GetCachedAvailableJavaMajors()
    {
        EnsureCacheLoaded();
        var majors = _memoryCache.Values
            .Where(static v => v >= 8)
            .Distinct()
            .Order()
            .ToList();

        return majors;
    }

    /// <summary>預載所有版本的 Java 需求；<paramref name="force"/> 為 true 時忽略快取</summary>
    public async Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(
        bool force = false,
        CancellationToken cancellationToken = default)
    {
        EnsureCacheLoaded();

        // 只抓取 Stable == true 且具備官方 server 下載連結之正式版本
        var mcVersions = await GetMinecraftVersionsWithServerAsync(cancellationToken).ConfigureAwait(false);
        var cache = _memoryCache;
        var toFetch = force
            ? [.. mcVersions]
            : mcVersions.Where(kv => !cache.ContainsKey(kv.Key)).ToList();

        if (toFetch.Count == 0)
        {
            return new Dictionary<string, int>(cache, StringComparer.OrdinalIgnoreCase);
        }

        Logger.Information("開始預載入 {Count} 個穩定版 Minecraft 版本的官方 Java major 需求", toFetch.Count);

        await Parallel.ForEachAsync(
            toFetch,
            new ParallelOptions { MaxDegreeOfParallelism = 10, CancellationToken = cancellationToken },
            async (pair, token) =>
            {
                int? major = await MojangVersionCatalog.FetchOfficialJavaMajorAsync(_httpPort, pair.Value, token).ConfigureAwait(false);
                if (major is > 0)
                {
                    _memoryCache[pair.Key] = major.Value;
                }
            }).ConfigureAwait(false);

        PersistCache();

        return new Dictionary<string, int>(_memoryCache, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>取得有官方 server.jar 的穩定版本及其 package URL；快取為空時改抓官方 Manifest</summary>
    private async Task<Dictionary<string, string>> GetMinecraftVersionsWithServerAsync(CancellationToken cancellationToken)
    {
        var result = MojangVersionCatalog.GetCachedReleasePackageUrls(_cacheDirectory);
        if (result.Count > 0)
        {
            return result;
        }

        var manifest = await MojangVersionCatalog.FetchManifestAsync(_httpPort, cancellationToken).ConfigureAwait(false);
        if (manifest is null)
        {
            return result;
        }

        var releases = manifest.Where(static v => v.Stable && !string.IsNullOrWhiteSpace(v.Url)).ToList();
        foreach (var v in releases)
        {
            result[v.Version] = v.Url!;
        }

        if (releases.Count > 0)
        {
            MojangVersionCatalog.SaveCachedVersions(MojangVersionCatalog.GetVersionsCachePath(_cacheDirectory), releases);
        }

        return result;
    }

    private void EnsureCacheLoaded()
    {
        if (_cacheLoaded)
        {
            return;
        }

        lock (_lock)
        {
            if (_cacheLoaded)
            {
                return;
            }

            MergeDiskCache(_memoryCache);
            _cacheLoaded = true;
        }
    }

    /// <summary>將磁碟上的官方與 Paper 版本快取併入指定字典；官方快取優先，Paper 快取（同取自 Mojang JSON）僅補缺</summary>
    private void MergeDiskCache(ConcurrentDictionary<string, int> target)
    {
        ReadOnlySpan<string> cachePaths = [
            MojangVersionCatalog.GetVersionsCachePath(_cacheDirectory),
            MojangVersionCatalog.GetPaperVersionsCachePath(_cacheDirectory)
        ];
        foreach (string cachePath in cachePaths)
        {
            foreach (var v in MojangVersionCatalog.LoadCachedVersions(cachePath))
            {
                if (!string.IsNullOrWhiteSpace(v.Version) && v.JavaMajor is > 0)
                {
                    target.TryAdd(v.Version.Trim(), Math.Max(MojangVersionCatalog.MinimumJavaMajor, v.JavaMajor.Value));
                }
            }
        }
    }

    /// <summary>捨棄記憶體快取並重新自磁碟載入；先建好新字典再整份替換，讀取端不會看到半空的快取</summary>
    public void ReloadCache()
    {
        lock (_lock)
        {
            var fresh = new ConcurrentDictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            MergeDiskCache(fresh);
            foreach (var kvp in _memoryCache)
            {
                fresh.TryAdd(kvp.Key, kvp.Value);
            }

            _memoryCache = fresh;
            _cacheLoaded = true;
        }
    }

    private static void SyncJavaMajorToCacheFile(
        string cachePath,
        ConcurrentDictionary<string, int> memoryCache,
        bool addNewEntries)
    {
        if (!addNewEntries && !SafeFileSystem.FileExists(cachePath))
        {
            return;
        }

        MojangVersionCatalog.UpdateCachedVersions(cachePath, versions =>
        {
            bool changed = false;
            var updated = new List<LoaderVersion>(versions.Count + (addNewEntries ? memoryCache.Count : 0));
            var seen = addNewEntries ? new HashSet<string>(StringComparer.OrdinalIgnoreCase) : null;

            foreach (var v in versions)
            {
                seen?.Add(v.Version);
                if (memoryCache.TryGetValue(v.Version, out int jm) && jm > 0 && v.JavaMajor != jm)
                {
                    updated.Add(v with { JavaMajor = jm });
                    changed = true;
                }
                else
                {
                    updated.Add(v);
                }
            }

            if (addNewEntries && seen is not null)
            {
                foreach (var kvp in memoryCache)
                {
                    if (kvp.Value > 0 && seen.Add(kvp.Key))
                    {
                        updated.Add(new LoaderVersion(kvp.Key, Stable: false, JavaMajor: kvp.Value));
                        changed = true;
                    }
                }
            }

            return changed ? updated : null;
        });
    }

    private void PersistCache()
    {
        lock (_lock)
        {
            var memoryCache = _memoryCache;
            try
            {
                SyncJavaMajorToCacheFile(MojangVersionCatalog.GetVersionsCachePath(_cacheDirectory), memoryCache, addNewEntries: true);
                SyncJavaMajorToCacheFile(MojangVersionCatalog.GetPaperVersionsCachePath(_cacheDirectory), memoryCache, addNewEntries: false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "持久化 Java requirements 快取失敗");
            }
        }
    }

    private async Task<int?> FetchJavaMajorFromOfficialAsync(
        string minecraftVersion,
        CancellationToken cancellationToken)
    {
        // 先查本機快取的 package URL，找不到再查官方 Manifest
        string? targetUrl = MojangVersionCatalog.TryGetCachedPackageUrl(_cacheDirectory, minecraftVersion);
        if (string.IsNullOrWhiteSpace(targetUrl))
        {
            var urls = await GetMinecraftVersionsWithServerAsync(cancellationToken).ConfigureAwait(false);
            urls.TryGetValue(minecraftVersion, out targetUrl);
        }

        if (string.IsNullOrWhiteSpace(targetUrl))
        {
            Logger.Warning("官方 Manifest 中未找到 Minecraft 版本: {Version}", minecraftVersion);
            return null;
        }

        return await MojangVersionCatalog.FetchOfficialJavaMajorAsync(_httpPort, targetUrl, cancellationToken).ConfigureAwait(false);
    }
}
