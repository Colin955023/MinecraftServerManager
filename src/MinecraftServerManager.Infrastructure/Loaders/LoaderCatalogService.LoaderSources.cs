using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderCatalogService
{
    private Task<IReadOnlyList<LoaderVersion>> FetchLoaderVersionsAsync(LoaderKind loader, CancellationToken cancellationToken) => loader switch
    {
        LoaderKind.Fabric => FetchMetaLoaderVersionsAsync("https://meta.fabricmc.net/v2/versions/loader", cancellationToken),
        LoaderKind.Quilt => FetchMetaLoaderVersionsAsync("https://meta.quiltmc.org/v3/versions/loader", cancellationToken),
        LoaderKind.Forge => FetchMavenVersionsAsync("https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml", isNeoForge: false, cancellationToken),
        LoaderKind.NeoForge => FetchMavenVersionsAsync("https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml", isNeoForge: true, cancellationToken),
        _ => Task.FromResult<IReadOnlyList<LoaderVersion>>([]),
    };

    /// <summary>取得 Fabric／Quilt 載入器版本（排除預發布）</summary>
    private async Task<IReadOnlyList<LoaderVersion>> FetchMetaLoaderVersionsAsync(string url, CancellationToken cancellationToken)
    {
        using var doc = await _httpPort.TryGetJsonDocumentAsync(new Uri(url), Logger, "抓取載入器版本清單失敗 ({Url})", cancellationToken).ConfigureAwait(false);
        if (doc is null || doc.RootElement.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        var list = new List<LoaderVersion>();
        foreach (var element in doc.RootElement.EnumerateArray())
        {
            if (element.GetStringOrNull("version") is { Length: > 0 } ver && !ContainsPreReleaseKeyword(ver))
            {
                list.Add(new LoaderVersion(ver, Stable: true));
            }
        }

        return list;
    }

    /// <summary>取得 Forge／NeoForge Maven 中繼資料內的版本清單</summary>
    private async Task<IReadOnlyList<LoaderVersion>> FetchMavenVersionsAsync(string url, bool isNeoForge, CancellationToken cancellationToken)
    {
        string? xml = await _httpPort.GetTextAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
        return string.IsNullOrWhiteSpace(xml) ? [] : ParseMavenMetadataXml(xml, isNeoForge);
    }

    [GeneratedRegex("<version>([^<]+)</version>", RegexOptions.CultureInvariant | RegexOptions.IgnoreCase)]
    private static partial Regex MavenVersionPattern();

    private static List<LoaderVersion> ParseMavenMetadataXml(string xmlContent, bool isNeoForge)
    {
        // 直接擷取 <version> 標籤，免載入 XML 解析器
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

            // Fabric／Quilt：只保留最新正式版
            return [.. versions
                .Where(static v => v.Stable && !ContainsPreReleaseKeyword(v.Version))
                .Take(1)];
        }

        if (loader == LoaderKind.Forge)
        {
            // Forge：保留最新 4 個，排除預發布版本
            return [.. versions
                .Where(v => string.Equals(v.MinecraftVersion, minecraftVersion, StringComparison.OrdinalIgnoreCase))
                .Where(static v => !ContainsPreReleaseKeyword(v.Version))
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

            // NeoForge：保留最新 4 個
            return [.. versions
                .Where(v => string.Equals(v.MinecraftVersion, minecraftVersion, StringComparison.OrdinalIgnoreCase)
                         || (isMc26Plus && string.Equals(v.MinecraftVersion, prefixedVersion, StringComparison.OrdinalIgnoreCase)))
                .OrderByDescending(VersionSortKey)
                .Take(4)];
        }

        return [];
    }

    /// <summary>以語意版本排序（47.10 大於 47.9）</summary>
    private static VersionValue VersionSortKey(LoaderVersion version) =>
        VersionValue.ParseOrZero(version.Version);
}
