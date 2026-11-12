using System.Text.Json;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

/// <summary>Minecraft 官方與 PaperMC 版本中繼資料、快取與 Java major 需求共用入口</summary>
internal static class MojangVersionCatalog
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MojangVersionCatalog));

    public const string VersionsCacheFileName = "mc_versions_cache.json";
    public const string PaperVersionsCacheFileName = "paper_mc_versions_cache.json";
    public const string ManifestV2Url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json";
    public const string ManifestFallbackUrl = "https://piston-meta.mojang.com/mc/game/version_manifest.json";
    public const string PaperProjectUrl = "https://fill.papermc.io/v3/projects/paper";

    public const int MinimumJavaMajor = 8;

    private static readonly string[] ManifestUrls = [ManifestV2Url, ManifestFallbackUrl];
    private static readonly Lock CacheLock = new();

    public static Uri PaperVersionUri(string minecraftVersion) =>
        new($"{PaperProjectUrl}/versions/{Uri.EscapeDataString(minecraftVersion.Trim())}");

    public static Uri PaperBuildsUri(string minecraftVersion) =>
        new($"{PaperProjectUrl}/versions/{Uri.EscapeDataString(minecraftVersion.Trim())}/builds");

    public static Uri PaperBuildUri(string minecraftVersion, string? build)
    {
        string segment = string.IsNullOrWhiteSpace(build) ? "latest" : Uri.EscapeDataString(build.Trim());
        return new($"{PaperProjectUrl}/versions/{Uri.EscapeDataString(minecraftVersion.Trim())}/builds/{segment}");
    }

    /// <summary>取得 Paper build 的下載描述：優先 <c>server:application</c>，否則取第一個含 <c>url</c> 的項目</summary>
    public static bool TryGetPaperDownload(JsonElement build, out JsonElement download)
    {
        download = default;
        if (!build.TryGetProperty("downloads", out var downloads) || downloads.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        if (downloads.TryGetProperty("server:application", out var application) && application.ValueKind == JsonValueKind.Object)
        {
            download = application;
            return true;
        }

        foreach (var property in downloads.EnumerateObject())
        {
            if (property.Value.ValueKind == JsonValueKind.Object && property.Value.TryGetProperty("url", out _))
            {
                download = property.Value;
                return true;
            }
        }

        return false;
    }

    public static string GetVersionsCachePath(string cacheDirectory) =>
        Path.Combine(cacheDirectory, VersionsCacheFileName);

    public static string GetPaperVersionsCachePath(string cacheDirectory) =>
        Path.Combine(cacheDirectory, PaperVersionsCacheFileName);

    /// <summary>讀取版本快取；檔案不存在或格式錯誤時回傳空清單</summary>
    public static List<LoaderVersion> LoadCachedVersions(string cachePath)
    {
        lock (CacheLock)
        {
            try
            {
                if (!SafeFileSystem.FileExists(cachePath))
                {
                    return [];
                }

                return JsonCodec.ReadFile<List<LoaderVersion>>(cachePath) ?? [];
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "讀取版本快取失敗: {Path}", cachePath);
                return [];
            }
        }
    }

    /// <summary>以原子寫入方式儲存版本快取</summary>
    public static void SaveCachedVersions(string cachePath, IReadOnlyList<LoaderVersion> versions)
    {
        lock (CacheLock)
        {
            try
            {
                AtomicFileWriter.WriteJson(cachePath, versions, indented: true);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "寫入版本快取失敗: {Path}", cachePath);
            }
        }
    }

    /// <summary>
    /// 在同一把鎖內「讀取最新快取 → 套用變更 → 原子寫回」，避免多個服務各自持舊快照寫回而互相覆蓋。
    /// <paramref name="update"/> 回傳 null 代表無變更（不寫檔）；回傳套用後的清單。
    /// </summary>
    public static IReadOnlyList<LoaderVersion> UpdateCachedVersions(
        string cachePath,
        Func<List<LoaderVersion>, IReadOnlyList<LoaderVersion>?> update)
    {
        ArgumentNullException.ThrowIfNull(update);
        lock (CacheLock)
        {
            var current = LoadCachedVersions(cachePath);
            if (update(current) is not { } updated)
            {
                return current;
            }

            SaveCachedVersions(cachePath, updated);
            return updated;
        }
    }

    /// <summary>自本機版本快取取得所有具官方 package URL 之正式版本（版本 → URL）</summary>
    public static Dictionary<string, string> GetCachedReleasePackageUrls(string cacheDirectory)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var version in LoadCachedVersions(GetVersionsCachePath(cacheDirectory)))
        {
            if (version.Stable && !string.IsNullOrWhiteSpace(version.Version) && !string.IsNullOrWhiteSpace(version.Url))
            {
                result[version.Version.Trim()] = version.Url.Trim();
            }
        }

        return result;
    }

    /// <summary>自本機版本快取查詢指定版本之官方 package URL</summary>
    public static string? TryGetCachedPackageUrl(string cacheDirectory, string minecraftVersion)
    {
        foreach (var version in LoadCachedVersions(GetVersionsCachePath(cacheDirectory)))
        {
            if (string.Equals(version.Version, minecraftVersion, StringComparison.OrdinalIgnoreCase)
                && !string.IsNullOrWhiteSpace(version.Url))
            {
                return version.Url;
            }
        }

        return null;
    }

    /// <summary>依序嘗試 Manifest V2 與後備網址取得官方版本清單並解析；兩者皆失敗時回傳 null</summary>
    public static async Task<List<LoaderVersion>?> FetchManifestAsync(IHttpPort httpPort, CancellationToken cancellationToken)
    {
        foreach (string url in ManifestUrls)
        {
            try
            {
                var response = await httpPort.GetJsonDocumentAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
                if (response is { IsSuccess: true, Payload: not null })
                {
                    using (response.Payload)
                    {
                        return ParseManifest(response.Payload);
                    }
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "抓取 Mojang Manifest 失敗 ({Url})", url);
            }
        }

        return null;
    }

    /// <summary>解析官方 Manifest：正式版僅保留具官方 server.jar 者並標記 Stable，其餘標記為非穩定版</summary>
    public static List<LoaderVersion> ParseManifest(JsonDocument doc)
    {
        if (doc.RootElement.ValueKind != JsonValueKind.Object
            || !doc.RootElement.TryGetProperty("versions", out var versionsElem)
            || versionsElem.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        var list = new List<LoaderVersion>();
        foreach (var elem in versionsElem.EnumerateArray())
        {
            string? id = elem.TryGetProperty("id", out var idProp) ? idProp.GetString() : null;
            if (string.IsNullOrEmpty(id))
            {
                continue;
            }

            string? type = elem.TryGetProperty("type", out var typeProp) ? typeProp.GetString() : null;
            string? url = elem.TryGetProperty("url", out var urlProp) ? urlProp.GetString() : null;

            if (string.Equals(type, "release", StringComparison.OrdinalIgnoreCase))
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

        return [.. list.OrderByDescending(static v => VersionValue.ParseOrZero(v.Version))];
    }

    /// <summary>官方 server.jar 自 1.2.5 起提供下載</summary>
    public static bool HasOfficialServerJar(string versionId)
    {
        if (!VersionValue.TryParse(versionId, out var v))
        {
            return false;
        }

        return v.Major > 1 || (v.Major == 1 && (v.Minor > 2 || (v.Minor == 2 && v.Patch >= 5)));
    }

    /// <summary>自 Mojang version package JSON 取得官方 Java major 需求</summary>
    public static async Task<int?> FetchOfficialJavaMajorAsync(IHttpPort httpPort, string packageUrl, CancellationToken cancellationToken)
    {
        try
        {
            var response = await httpPort.GetJsonDocumentAsync(new Uri(packageUrl), cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccess || response.Payload is null)
            {
                return null;
            }

            using (response.Payload)
            {
                return ParseJavaMajorFromVersionJson(response.Payload.RootElement);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "抓取版本 package JSON 失敗 ({Url})", packageUrl);
            return null;
        }
    }

    /// <summary>自 PaperMC API 取得指定 Minecraft 版本之最低 Java major（下限為 Java 8）</summary>
    public static async Task<int?> FetchPaperJavaMajorAsync(IHttpPort httpPort, string minecraftVersion, CancellationToken cancellationToken)
    {
        try
        {
            var response = await httpPort.GetJsonDocumentAsync(PaperVersionUri(minecraftVersion), cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccess || response.Payload is null)
            {
                return null;
            }

            using var doc = response.Payload;
            if (doc.RootElement.TryGetProperty("version", out var vProp) &&
                vProp.TryGetProperty("java", out var jProp) &&
                jProp.TryGetProperty("version", out var jvProp) &&
                jvProp.TryGetProperty("minimum", out var minProp) &&
                minProp.TryGetInt32(out int minimum))
            {
                return Math.Max(MinimumJavaMajor, minimum);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "從 Paper API 取得 Java 最低版本失敗");
        }

        return null;
    }

    /// <summary>解析 Minecraft version package JSON 中的 javaVersion.majorVersion 或 java_version.major</summary>
    public static int? ParseJavaMajorFromVersionJson(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        // 1. 標準 Mojang 結構: { "javaVersion": { "component": "...", "majorVersion": 21 } }
        if (root.TryGetProperty("javaVersion", out var jvElem) && jvElem.ValueKind == JsonValueKind.Object
            && jvElem.TryGetProperty("majorVersion", out var mvElem) && mvElem.TryGetInt32(out int mv) && mv > 0)
        {
            return mv;
        }

        // 2. 替代結構: { "java_version": { "major": 17 } }
        if (root.TryGetProperty("java_version", out var jvElem2) && jvElem2.ValueKind == JsonValueKind.Object
            && jvElem2.TryGetProperty("major", out var mvElem2) && mvElem2.TryGetInt32(out int mv2) && mv2 > 0)
        {
            return mv2;
        }

        // 3. Mojang 官方套件規格：合法 version package 但未定義 javaVersion 欄位者，官方啟動器標準皆指派 jre-legacy (Java 8)
        if (root.TryGetProperty("id", out _) && (root.TryGetProperty("downloads", out _) || root.TryGetProperty("libraries", out _)))
        {
            return MinimumJavaMajor;
        }

        return null;
    }
}
