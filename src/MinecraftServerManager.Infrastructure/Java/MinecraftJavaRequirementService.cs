using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

/// <summary>
/// Minecraft 版本 Java major 需求服務實作。
/// 完全依據 Mojang 官方 version package JSON 的 javaVersion.majorVersion 動態取得並快取，
/// 嚴格禁止依據版本號進行硬編碼推算。
/// </summary>
public sealed class MinecraftJavaRequirementService : IMinecraftJavaRequirementService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("MinecraftJavaRequirementService");

    public const string RequirementsCacheFileName = "mc_java_requirements_cache.json";
    public const string VersionsCacheFileName = "mc_versions_cache.json";
    public const string ManifestV2Url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json";
    public const string ManifestFallbackUrl = "https://piston-meta.mojang.com/mc/game/version_manifest.json";

    private readonly IHttpPort _httpPort;
    private readonly string _cacheDirectory;
    private readonly ConcurrentDictionary<string, int> _memoryCache = new(StringComparer.OrdinalIgnoreCase);
    private readonly object _lock = new();
    private bool _cacheLoaded;

    public MinecraftJavaRequirementService(IHttpPort httpPort, string? cacheDirectory = null)
    {
        _httpPort = httpPort ?? throw new ArgumentNullException(nameof(httpPort));
        _cacheDirectory = SafeFileSystem.ResolveStableDirectory(
            string.IsNullOrWhiteSpace(cacheDirectory) ? RuntimePaths.GetVersionCacheDir() : cacheDirectory,
            create: true);
    }

    /// <inheritdoc />
    public async Task<int> GetRequiredJavaMajorAsync(
        string minecraftVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(minecraftVersion);

        string cleaned = minecraftVersion.Trim();
        EnsureCacheLoaded();

        if (_memoryCache.TryGetValue(cleaned, out int cachedMajor) && cachedMajor > 0)
        {
            return cachedMajor;
        }

        // 快取未命中：自官方 Manifest 與版本 Package JSON 動態抓取
        int? remoteMajor = await FetchJavaMajorFromOfficialAsync(cleaned, cancellationToken).ConfigureAwait(false);
        if (remoteMajor is > 0)
        {
            _memoryCache[cleaned] = remoteMajor.Value;
            PersistCache();
            return remoteMajor.Value;
        }

        throw new InvalidOperationException($"無法從 Mojang 官方版本資訊取得 Minecraft 版本「{cleaned}」指定的 Java major 版本。");
    }

    /// <inheritdoc />
    public int? GetCachedJavaMajor(string minecraftVersion)
    {
        if (string.IsNullOrWhiteSpace(minecraftVersion))
        {
            return null;
        }

        string cleaned = minecraftVersion.Trim();
        EnsureCacheLoaded();

        if (_memoryCache.TryGetValue(cleaned, out int cachedMajor) && cachedMajor > 0)
        {
            return cachedMajor;
        }

        return null;
    }

    /// <inheritdoc />
    public async Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(
        bool force = false,
        CancellationToken cancellationToken = default)
    {
        EnsureCacheLoaded();

        var versionUrls = await GetOfficialVersionUrlsAsync(cancellationToken).ConfigureAwait(false);
        if (versionUrls.Count == 0)
        {
            return new Dictionary<string, int>(_memoryCache, StringComparer.OrdinalIgnoreCase);
        }

        var toFetch = force
            ? versionUrls
            : versionUrls.Where(kv => !_memoryCache.ContainsKey(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);

        if (toFetch.Count == 0)
        {
            return new Dictionary<string, int>(_memoryCache, StringComparer.OrdinalIgnoreCase);
        }

        Logger.Information("開始預載入 {Count} 個 Minecraft 版本的官方 Java major 需求", toFetch.Count);

        using var throttler = new SemaphoreSlim(10, 10);
        var tasks = toFetch.Select(async pair =>
        {
            await throttler.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                int? major = await FetchJavaMajorFromUrlAsync(pair.Value, cancellationToken).ConfigureAwait(false);
                if (major is > 0)
                {
                    _memoryCache[pair.Key] = major.Value;
                }
            }
            catch (Exception ex)
            {
                Logger.Debug("預載入版本 {Version} 的官方 Java major 失敗: {Error}", pair.Key, ex.Message);
            }
            finally
            {
                throttler.Release();
            }
        });

        await Task.WhenAll(tasks).ConfigureAwait(false);
        PersistCache();

        return new Dictionary<string, int>(_memoryCache, StringComparer.OrdinalIgnoreCase);
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

            string cachePath = Path.Combine(_cacheDirectory, RequirementsCacheFileName);
            if (File.Exists(cachePath))
            {
                try
                {
                    string json = File.ReadAllText(cachePath, Encoding.UTF8);
                    using var doc = JsonDocument.Parse(json);
                    if (doc.RootElement.ValueKind == JsonValueKind.Object)
                    {
                        foreach (var prop in doc.RootElement.EnumerateObject())
                        {
                            if (prop.Value.TryGetInt32(out int major) && major > 0)
                            {
                                _memoryCache[prop.Name.Trim()] = major;
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("讀取 Java requirements 快取失敗 ({Path}): {Error}", cachePath, ex.Message);
                }
            }

            _cacheLoaded = true;
        }
    }

    private void PersistCache()
    {
        lock (_lock)
        {
            try
            {
                string cachePath = Path.Combine(_cacheDirectory, RequirementsCacheFileName);

                var sorted = _memoryCache
                    .OrderByDescending(kv => VersionValue.TryParse(kv.Key, out var v) ? v : VersionValue.Zero)
                    .ThenByDescending(kv => kv.Key, StringComparer.OrdinalIgnoreCase)
                    .ToDictionary(kv => kv.Key, kv => kv.Value);

                string json = JsonCodec.Serialize(sorted, indented: true);
                AtomicFileWriter.WriteText(cachePath, json);
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
        // 1. 優先從本地 mc_versions_cache.json 尋找 URL
        string? targetUrl = TryFindPackageUrlFromLocalCache(minecraftVersion);

        // 2. 本地找不到時向 Mojang 官方 Manifest 查詢
        if (string.IsNullOrWhiteSpace(targetUrl))
        {
            var urls = await GetOfficialVersionUrlsAsync(cancellationToken).ConfigureAwait(false);
            urls.TryGetValue(minecraftVersion, out targetUrl);
        }

        if (string.IsNullOrWhiteSpace(targetUrl))
        {
            Logger.Debug("官方 Manifest 中未找到 Minecraft 版本: {Version}", minecraftVersion);
            return null;
        }

        return await FetchJavaMajorFromUrlAsync(targetUrl, cancellationToken).ConfigureAwait(false);
    }

    private string? TryFindPackageUrlFromLocalCache(string minecraftVersion)
    {
        try
        {
            string versionsCachePath = Path.Combine(_cacheDirectory, VersionsCacheFileName);
            if (!File.Exists(versionsCachePath))
            {
                return null;
            }

            string json = File.ReadAllText(versionsCachePath, Encoding.UTF8);
            using var doc = JsonDocument.Parse(json);

            if (doc.RootElement.ValueKind == JsonValueKind.Array)
            {
                foreach (var elem in doc.RootElement.EnumerateArray())
                {
                    string? id = null;
                    if (elem.TryGetProperty("Version", out var vProp))
                    {
                        id = vProp.GetString();
                    }
                    else if (elem.TryGetProperty("id", out var idProp))
                    {
                        id = idProp.GetString();
                    }

                    if (string.Equals(id, minecraftVersion, StringComparison.OrdinalIgnoreCase))
                    {
                        if (elem.TryGetProperty("Url", out var uProp))
                        {
                            return uProp.GetString();
                        }
                        if (elem.TryGetProperty("url", out var urlProp))
                        {
                            return urlProp.GetString();
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Logger.Debug("自本機 mc_versions_cache.json 讀取版本 URL 失敗: {Error}", ex.Message);
        }

        return null;
    }

    private async Task<Dictionary<string, string>> GetOfficialVersionUrlsAsync(CancellationToken cancellationToken)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        string? manifestJson = null;
        try
        {
            manifestJson = await _httpPort.GetTextAsync(new Uri(ManifestV2Url), cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            try
            {
                manifestJson = await _httpPort.GetTextAsync(new Uri(ManifestFallbackUrl), cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                Logger.Debug("抓取 Mojang Manifest 失敗: {Error}", ex.Message);
            }
        }

        if (string.IsNullOrWhiteSpace(manifestJson))
        {
            string versionsCachePath = Path.Combine(_cacheDirectory, VersionsCacheFileName);
            if (File.Exists(versionsCachePath))
            {
                try
                {
                    manifestJson = await File.ReadAllTextAsync(versionsCachePath, cancellationToken).ConfigureAwait(false);
                }
                catch
                {
                }
            }
        }

        if (string.IsNullOrWhiteSpace(manifestJson))
        {
            return result;
        }

        try
        {
            using var doc = JsonDocument.Parse(manifestJson);
            JsonElement arrayElement;

            if (doc.RootElement.ValueKind == JsonValueKind.Object &&
                doc.RootElement.TryGetProperty("versions", out var vElem) &&
                vElem.ValueKind == JsonValueKind.Array)
            {
                arrayElement = vElem;
            }
            else if (doc.RootElement.ValueKind == JsonValueKind.Array)
            {
                arrayElement = doc.RootElement;
            }
            else
            {
                return result;
            }

            foreach (var elem in arrayElement.EnumerateArray())
            {
                string? id = null;
                string? url = null;

                if (elem.TryGetProperty("id", out var idProp))
                {
                    id = idProp.GetString();
                }
                else if (elem.TryGetProperty("Version", out var vProp))
                {
                    id = vProp.GetString();
                }

                if (elem.TryGetProperty("url", out var urlProp))
                {
                    url = urlProp.GetString();
                }
                else if (elem.TryGetProperty("Url", out var uProp))
                {
                    url = uProp.GetString();
                }

                if (!string.IsNullOrWhiteSpace(id) && !string.IsNullOrWhiteSpace(url))
                {
                    result[id.Trim()] = url.Trim();
                }
            }
        }
        catch (Exception ex)
        {
            Logger.Debug("解析 Manifest 版本 JSON 清單失敗: {Error}", ex.Message);
        }

        return result;
    }

    private async Task<int?> FetchJavaMajorFromUrlAsync(string url, CancellationToken cancellationToken)
    {
        try
        {
            string? json = await _httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                return null;
            }

            return ParseJavaMajorFromVersionJson(json);
        }
        catch (Exception ex)
        {
            Logger.Debug("抓取版本 package JSON 失敗 ({Url}): {Error}", url, ex.Message);
            return null;
        }
    }

    /// <summary>
    /// 解析 Minecraft version package JSON 中的 javaVersion.majorVersion 或 java_version.major
    /// </summary>
    public static int? ParseJavaMajorFromVersionJson(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return null;
        }

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        // 1. 標準 Mojang 結構: { "javaVersion": { "component": "...", "majorVersion": 21 } }
        if (root.TryGetProperty("javaVersion", out var jvElem) && jvElem.ValueKind == JsonValueKind.Object)
        {
            if (jvElem.TryGetProperty("majorVersion", out var mvElem) && mvElem.TryGetInt32(out int mv) && mv > 0)
            {
                return mv;
            }
        }

        // 2. 替代結構: { "java_version": { "major": 17 } }
        if (root.TryGetProperty("java_version", out var jvElem2) && jvElem2.ValueKind == JsonValueKind.Object)
        {
            if (jvElem2.TryGetProperty("major", out var mvElem2) && mvElem2.TryGetInt32(out int mv2) && mv2 > 0)
            {
                return mv2;
            }
        }

        return null;
    }
}
