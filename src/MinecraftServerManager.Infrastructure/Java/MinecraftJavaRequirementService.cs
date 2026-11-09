using System.Collections.Concurrent;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Java;

/// <summary>
/// Minecraft 版本 Java major 需求服務實作。
/// 完全依據 Mojang 官方 version package JSON 的 javaVersion.majorVersion 動態取得並快取，
/// 嚴格禁止依據版本號做硬編碼推算。
/// </summary>
public sealed class MinecraftJavaRequirementService : IMinecraftJavaRequirementService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MinecraftJavaRequirementService));

    private readonly IHttpPort _httpPort;
    private readonly string _cacheDirectory;
    private readonly ConcurrentDictionary<string, int> _memoryCache = new(StringComparer.OrdinalIgnoreCase);
    private readonly Lock _lock = new();
    private volatile bool _cacheLoaded;

    public MinecraftJavaRequirementService(IHttpPort httpPort, string cacheDirectory)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        ArgumentException.ThrowIfNullOrWhiteSpace(cacheDirectory);
        _httpPort = httpPort;
        _cacheDirectory = SafeFileSystem.ResolveStableDirectory(cacheDirectory, create: true);
    }

    /// <inheritdoc />
    public async Task<int> GetRequiredJavaMajorAsync(
        string minecraftVersion,
        LoaderKind loader = LoaderKind.Unknown,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(minecraftVersion);

        string cleaned = minecraftVersion.Trim();
        EnsureCacheLoaded();

        string cacheKey = loader == LoaderKind.Paper ? $"paper:{cleaned}" : cleaned;
        if (_memoryCache.TryGetValue(cacheKey, out int cachedMajor) && cachedMajor > 0)
        {
            return cachedMajor;
        }

        if (loader == LoaderKind.Paper)
        {
            int? paperMajor = await MojangVersionCatalog.FetchPaperJavaMajorAsync(_httpPort, cleaned, cancellationToken).ConfigureAwait(false);
            if (paperMajor is > 0)
            {
                _memoryCache[cacheKey] = paperMajor.Value;
                PersistCache();
                return paperMajor.Value;
            }
        }

        // 快取未命中：自官方 Manifest 與版本 Package JSON 動態抓取
        int? remoteMajor = await FetchJavaMajorFromOfficialAsync(cleaned, cancellationToken).ConfigureAwait(false);
        if (remoteMajor is > 0)
        {
            _memoryCache[cleaned] = remoteMajor.Value;
            if (loader == LoaderKind.Paper)
            {
                _memoryCache[cacheKey] = remoteMajor.Value;
            }
            PersistCache();
            return remoteMajor.Value;
        }

        throw new InvalidOperationException($"無法從 Mojang 官方或載入器版本資訊取得 Minecraft 版本「{cleaned}」指定的 Java major 版本。");
    }

    /// <inheritdoc />
    public int? GetCachedJavaMajor(string minecraftVersion, LoaderKind loader = LoaderKind.Unknown)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return null;
        }

        string cleaned = minecraftVersion.Trim();
        EnsureCacheLoaded();

        string cacheKey = loader == LoaderKind.Paper ? $"paper:{cleaned}" : cleaned;
        if (_memoryCache.TryGetValue(cacheKey, out int cachedMajor) && cachedMajor > 0)
        {
            return cachedMajor;
        }

        if (loader == LoaderKind.Paper && _memoryCache.TryGetValue(cleaned, out int fallbackMajor) && fallbackMajor > 0)
        {
            return fallbackMajor;
        }

        return null;
    }

    /// <inheritdoc />
    public IReadOnlyList<int> GetCachedAvailableJavaMajors()
    {
        EnsureCacheLoaded();
        var majors = _memoryCache.Values
            .Where(static v => v >= 8)
            .Distinct()
            .Order()
            .ToList();

        return majors.Count > 0 ? majors : [8, 11, 16, 17, 21];
    }

    /// <inheritdoc />
    public async Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(
        bool force = false,
        CancellationToken cancellationToken = default)
    {
        EnsureCacheLoaded();

        // 只抓取 Stable == true 且具備官方 server 下載連結之正式版本
        var mcVersions = await GetMinecraftVersionsWithServerAsync(cancellationToken).ConfigureAwait(false);
        var toFetch = force
            ? [.. mcVersions]
            : mcVersions.Where(kv => !_memoryCache.ContainsKey(kv.Key)).ToList();

        if (toFetch.Count == 0)
        {
            return new Dictionary<string, int>(_memoryCache, StringComparer.OrdinalIgnoreCase);
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

    /// <summary>
    /// 取得所有 Stable == true 且具備官方 server.jar 下載連結的 Minecraft 版本及其 package URL。
    /// 本機版本快取為空時改自 Mojang 官方 Manifest 取得並寫回快取。
    /// </summary>
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

            foreach (var v in MojangVersionCatalog.LoadCachedVersions(MojangVersionCatalog.GetPaperVersionsCachePath(_cacheDirectory)))
            {
                if (!string.IsNullOrWhiteSpace(v.Version) && v.JavaMajor is > 0)
                {
                    _memoryCache[$"paper:{v.Version.Trim()}"] = Math.Max(MojangVersionCatalog.MinimumJavaMajor, v.JavaMajor.Value);
                }
            }

            foreach (var v in MojangVersionCatalog.LoadCachedVersions(MojangVersionCatalog.GetVersionsCachePath(_cacheDirectory)))
            {
                if (!string.IsNullOrWhiteSpace(v.Version) && v.JavaMajor is > 0)
                {
                    _memoryCache.TryAdd(v.Version.Trim(), Math.Max(MojangVersionCatalog.MinimumJavaMajor, v.JavaMajor.Value));
                }
            }

            _cacheLoaded = true;
        }
    }

    /// <inheritdoc />
    public void ReloadCache()
    {
        lock (_lock)
        {
            _cacheLoaded = false;
            EnsureCacheLoaded();
        }
    }

    private void PersistCache()
    {
        lock (_lock)
        {
            try
            {
                // 1. 同步更新官方 MC 快取 mc_versions_cache.json
                string mcCachePath = MojangVersionCatalog.GetVersionsCachePath(_cacheDirectory);
                var mcVersions = SafeFileSystem.FileExists(mcCachePath) ? MojangVersionCatalog.LoadCachedVersions(mcCachePath) : [];
                bool mcChanged = false;
                var updatedMc = new List<LoaderVersion>(mcVersions.Count + _memoryCache.Count);
                var seenMc = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

                foreach (var v in mcVersions)
                {
                    seenMc.Add(v.Version);
                    if (_memoryCache.TryGetValue(v.Version, out int jm) && jm > 0 && v.JavaMajor != jm)
                    {
                        updatedMc.Add(v with { JavaMajor = jm });
                        mcChanged = true;
                    }
                    else
                    {
                        updatedMc.Add(v);
                    }
                }

                foreach (var kvp in _memoryCache)
                {
                    if (!kvp.Key.Contains(':') && kvp.Value > 0 && seenMc.Add(kvp.Key))
                    {
                        updatedMc.Add(new LoaderVersion(kvp.Key, Stable: true, JavaMajor: kvp.Value));
                        mcChanged = true;
                    }
                }

                if (mcChanged)
                {
                    MojangVersionCatalog.SaveCachedVersions(mcCachePath, updatedMc);
                }

                // 2. 同步更新 Paper 快取 paper_mc_versions_cache.json
                string paperCachePath = MojangVersionCatalog.GetPaperVersionsCachePath(_cacheDirectory);
                if (SafeFileSystem.FileExists(paperCachePath))
                {
                    var paperVersions = MojangVersionCatalog.LoadCachedVersions(paperCachePath);
                    bool paperChanged = false;
                    var updatedPaper = new List<LoaderVersion>(paperVersions.Count);
                    foreach (var v in paperVersions)
                    {
                        if (_memoryCache.TryGetValue($"paper:{v.Version}", out int jm) && jm > 0 && v.JavaMajor != jm)
                        {
                            updatedPaper.Add(v with { JavaMajor = jm });
                            paperChanged = true;
                        }
                        else
                        {
                            updatedPaper.Add(v);
                        }
                    }

                    if (paperChanged)
                    {
                        MojangVersionCatalog.SaveCachedVersions(paperCachePath, updatedPaper);
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warning("持久化 Java requirements 快取失敗: {Error}", ex.Message);
            }
        }
    }

    private async Task<int?> FetchJavaMajorFromOfficialAsync(
        string minecraftVersion,
        CancellationToken cancellationToken)
    {
        // 1. 優先從本地版本快取尋找 package URL；2. 找不到時向 Mojang 官方 Manifest 查詢
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
