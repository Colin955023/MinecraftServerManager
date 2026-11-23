using System.Collections.Frozen;
using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Text.Json;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

/// <summary>Minecraft 與 Paper 版本中繼資料、快取與 Java major 共用入口</summary>
internal static class MojangVersionCatalog
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MojangVersionCatalog));

    internal const string VersionsCacheFileName = "mc_versions_cache.json";
    private const string PaperVersionsCacheFileName = "paper_mc_versions_cache.json";
    internal const string ManifestV2Url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json";
    internal const string ManifestFallbackUrl = "https://piston-meta.mojang.com/mc/game/version_manifest.json";
    public const string PaperProjectUrl = "https://fill.papermc.io/v3/projects/paper";

    public const int MinimumJavaMajor = 8;

    private static readonly string[] ManifestUrls = [ManifestV2Url, ManifestFallbackUrl];
    private static readonly FrozenSet<string> OfficialPackageHosts =
        TrustedHostPolicy.Hosts("piston-meta.mojang.com", "launchermeta.mojang.com");

    // 依快取路徑分條上鎖，不同快取檔互不阻塞
    private static readonly Lock[] CacheLocks = [new(), new(), new(), new(), new(), new(), new(), new()];

    private static Lock GetCacheLock(string cachePath)
    {
        int hash = StringComparer.OrdinalIgnoreCase.GetHashCode(Path.GetFullPath(cachePath));
        return CacheLocks[(int)((uint)hash % (uint)CacheLocks.Length)];
    }

    /// <summary>版本 package JSON 須為 Mojang 官方 HTTPS 位址（預設埠、無使用者資訊）</summary>
    public static bool IsOfficialPackageUrl([NotNullWhen(true)] string? url) =>
        TrustedHostPolicy.IsTrusted(url, OfficialPackageHosts);

    public static Uri PaperBuildsUri(string minecraftVersion) =>
        new($"{PaperProjectUrl}/versions/{Uri.EscapeDataString(minecraftVersion.Trim())}/builds");

    public static Uri PaperBuildUri(string minecraftVersion, string? build)
    {
        string segment = string.IsNullOrWhiteSpace(build) ? "latest" : Uri.EscapeDataString(build.Trim());
        return new($"{PaperProjectUrl}/versions/{Uri.EscapeDataString(minecraftVersion.Trim())}/builds/{segment}");
    }

    /// <summary>取得 Paper build 下載描述：優先 <c>server:application</c>，否則取第一個含 <c>url</c> 者</summary>
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
        lock (GetCacheLock(cachePath))
        {
            return LoadCachedCore(cachePath);
        }
    }

    /// <summary>以原子寫入方式儲存版本快取</summary>
    public static void SaveCachedVersions(string cachePath, IReadOnlyList<LoaderVersion> versions)
    {
        lock (GetCacheLock(cachePath))
        {
            SaveCachedCore(cachePath, versions);
        }
    }

    /// <summary>於同一把鎖內讀取、套用變更並寫回快取；<paramref name="update"/> 回傳 null 表示無變更</summary>
    public static IReadOnlyList<LoaderVersion> UpdateCachedVersions(
        string cachePath,
        Func<List<LoaderVersion>, IReadOnlyList<LoaderVersion>?> update)
    {
        ArgumentNullException.ThrowIfNull(update);
        lock (GetCacheLock(cachePath))
        {
            var current = LoadCachedCore(cachePath);
            if (update(current) is not { } updated)
            {
                return current;
            }

            SaveCachedCore(cachePath, updated);
            return updated;
        }
    }

    private static List<LoaderVersion> LoadCachedCore(string cachePath) =>
        JsonCodec.TryReadFile<List<LoaderVersion>>(cachePath) ?? [];

    private static void SaveCachedCore(string cachePath, IReadOnlyList<LoaderVersion> versions)
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

    /// <summary>自快取取得有官方 package URL 的正式版本（版本 → URL）</summary>
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

    /// <summary>取得官方版本清單（V2 優先，失敗用後備網址）；皆失敗回傳 null</summary>
    public static async Task<List<LoaderVersion>?> FetchManifestAsync(IHttpPort httpPort, CancellationToken cancellationToken)
    {
        foreach (string url in ManifestUrls)
        {
            using var doc = await httpPort.TryGetJsonDocumentAsync(new Uri(url), Logger, "抓取 Mojang Manifest 失敗 ({Url})", cancellationToken).ConfigureAwait(false);
            if (doc is not null)
            {
                return ParseManifest(doc);
            }
        }

        return null;
    }

    /// <summary>解析官方 Manifest；有官方 server.jar 的正式版標記為穩定，依 <c>releaseTime</c> 由新到舊排序</summary>
    internal static List<LoaderVersion> ParseManifest(JsonDocument doc)
    {
        if (!doc.RootElement.TryGetProperty("versions", JsonValueKind.Array, out var versionsElem))
        {
            return [];
        }

        var list = new List<(LoaderVersion Version, DateTimeOffset ReleaseTime)>();
        foreach (var elem in versionsElem.EnumerateArray())
        {
            string? id = elem.GetStringOrNull("id");
            if (string.IsNullOrEmpty(id))
            {
                continue;
            }

            string? type = elem.GetStringOrNull("type");
            string? url = elem.GetStringOrNull("url");
            if (!IsOfficialPackageUrl(url))
            {
                url = null;
            }

            bool isRelease = string.Equals(type, "release", StringComparison.OrdinalIgnoreCase);
            if (isRelease && !HasOfficialServerJar(id))
            {
                continue;
            }

            // 週快照版號無法以數字比較，缺 releaseTime 時排最後
            DateTimeOffset releaseTime = DateTimeOffset.TryParse(
                elem.GetStringOrNull("releaseTime"),
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal,
                out var parsed)
                ? parsed
                : DateTimeOffset.MinValue;
            list.Add((new LoaderVersion(id, Url: url, Stable: isRelease), releaseTime));
        }

        return
        [
            .. list
                .OrderByDescending(static item => item.ReleaseTime)
                .ThenByDescending(static item => VersionValue.ParseOrZero(item.Version.Version))
                .Select(static item => item.Version),
        ];
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

    public static async Task<int?> FetchOfficialJavaMajorAsync(IHttpPort httpPort, string packageUrl, CancellationToken cancellationToken)
    {
        if (!IsOfficialPackageUrl(packageUrl))
        {
            Logger.Warning("略過非 Mojang 官方版本 package 位址: {Url}", packageUrl);
            return null;
        }

        using var doc = await httpPort.TryGetJsonDocumentAsync(new Uri(packageUrl), Logger, "抓取版本 package JSON 失敗 ({Url})", cancellationToken).ConfigureAwait(false);
        return doc is null ? null : ParseJavaMajorFromVersionJson(doc.RootElement);
    }

    /// <summary>解析 javaVersion.majorVersion 或 java_version.major</summary>
    internal static int? ParseJavaMajorFromVersionJson(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        // 1. 標準 Mojang 結構: { "javaVersion": { "component": "...", "majorVersion": 21 } }
        if (root.TryGetProperty("javaVersion", JsonValueKind.Object, out var jvElem)
            && jvElem.GetInt32OrNull("majorVersion") is > 0 and int mv)
        {
            return mv;
        }

        // 2. 替代結構: { "java_version": { "major": 17 } }
        if (root.TryGetProperty("java_version", JsonValueKind.Object, out var jvElem2)
            && jvElem2.GetInt32OrNull("major") is > 0 and int mv2)
        {
            return mv2;
        }

        // 3. 未定義 javaVersion 的舊版為 jre-legacy（Java 8）
        if (root.TryGetProperty("id", out _) && (root.TryGetProperty("downloads", out _) || root.TryGetProperty("libraries", out _)))
        {
            return MinimumJavaMajor;
        }

        return null;
    }
}
