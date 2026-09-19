using System.Text.Json;
using System.Xml.Linq;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;
using MinecraftServerManager.Core.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed class LoaderCatalogService(IHttpPort httpPort, string cacheDirectory) : ILoaderCatalogService
{
    private readonly string _cacheDir = SafeFileSystem.ResolveStableDirectory(cacheDirectory, create: true);
    private readonly TimeSpan _cacheTtl = TimeSpan.FromHours(12);

    public async Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        string cacheFile = Path.Combine(_cacheDir, "mc_versions_cache.json");

        if (IsCacheFresh(cacheFile))
        {
            var cached = LoadCachedVersions(cacheFile);
            if (cached.Count > 0)
            {
                return FilterMinecraftVersions(cached, includeSnapshots);
            }
        }

        try
        {
            string manifestUrl = "https://piston-meta.mojang.com/mc/game/version_manifest.json";
            string? json = await httpPort.GetTextAsync(new Uri(manifestUrl), cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                return [];
            }

            var parsed = ParseMinecraftManifest(json);

            if (parsed.Count > 0)
            {
                SaveCachedVersions(cacheFile, parsed);
                return FilterMinecraftVersions(parsed, includeSnapshots);
            }
        }
        catch
        {
            // 遠端失敗時嘗試過期快取
            if (File.Exists(cacheFile))
            {
                var stale = LoadCachedVersions(cacheFile);
                if (stale.Count > 0)
                {
                    return FilterMinecraftVersions(stale, includeSnapshots);
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

        if (loader == LoaderKind.Vanilla)
        {
            return [new LoaderVersion(minecraftVersion, Stable: true, MinecraftVersion: minecraftVersion)];
        }

        string cacheFile = Path.Combine(_cacheDir, $"{loader.ToString().ToLowerInvariant()}_versions_cache.json");

        if (IsCacheFresh(cacheFile))
        {
            var cached = LoadCachedVersions(cacheFile);
            var filtered = FilterLoaderByMcVersion(cached, loader, minecraftVersion);
            if (filtered.Count > 0)
            {
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
                SaveCachedVersions(cacheFile, fetched);
                return FilterLoaderByMcVersion(fetched, loader, minecraftVersion);
            }
        }
        catch
        {
            if (File.Exists(cacheFile))
            {
                var stale = LoadCachedVersions(cacheFile);
                return FilterLoaderByMcVersion(stale, loader, minecraftVersion);
            }
        }

        return [];
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
                if (string.IsNullOrWhiteSpace(ver))
                {
                    continue;
                }

                bool stable = element.TryGetProperty("stable", out var sProp) && sProp.GetBoolean();
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
                if (string.IsNullOrWhiteSpace(ver))
                {
                    continue;
                }

                bool stable = element.TryGetProperty("stable", out var sProp) && sProp.GetBoolean();
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
        var loaders = new[] { LoaderKind.Fabric, LoaderKind.Quilt, LoaderKind.Forge, LoaderKind.NeoForge };
        foreach (var loader in loaders)
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
                    SaveCachedVersions(cacheFile, fetched);
                }
            }
            catch
            {
            }
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
            string? json = await httpPort.GetTextAsync(new Uri(manifestUrl), cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(json))
            {
                var fetched = ParseMinecraftManifest(json);
                if (fetched.Count > 0)
                {
                    var mergedMap = new Dictionary<string, LoaderVersion>(StringComparer.OrdinalIgnoreCase);
                    foreach (var v in fetched)
                    {
                        mergedMap[v.Version] = v;
                    }
                    foreach (var v in existing)
                    {
                        mergedMap.TryAdd(v.Version, v);
                    }
                    var merged = mergedMap.Values
                        .OrderByDescending(v => VersionValue.TryParse(v.Version, out var val) ? val : VersionValue.Zero)
                        .ToList();

                    SaveCachedVersions(cacheFile, merged);
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
        var doc = XDocument.Parse(xmlContent, LoadOptions.None);
        var versions = doc.Descendants("version")
            .Select(x => x.Value.Trim())
            .Where(x => !string.IsNullOrEmpty(x))
            .Distinct()
            .ToList();

        var list = new List<LoaderVersion>();
        foreach (string? raw in versions)
        {
            if (isNeoForge)
            {
                string? mcVer = DeriveMinecraftVersionFromNeoForge(raw);
                bool isStable = !raw.Contains("beta", StringComparison.OrdinalIgnoreCase) && !raw.Contains("alpha", StringComparison.OrdinalIgnoreCase);
                list.Add(new LoaderVersion(raw, Stable: isStable, MinecraftVersion: mcVer));
            }
            else
            {
                int dashIndex = raw.IndexOf('-');
                if (dashIndex > 0)
                {
                    string mcVer = raw[..dashIndex];
                    string loaderVer = raw[(dashIndex + 1)..];
                    list.Add(new LoaderVersion(loaderVer, Stable: true, MinecraftVersion: mcVer));
                }
            }
        }

        return list;
    }

    private static string? DeriveMinecraftVersionFromNeoForge(string rawVersion)
    {
        string[] parts = rawVersion.Split('.');
        if (parts.Length >= 2 && int.TryParse(parts[0], out int major))
        {
            if (major >= 20)
            {
                string minor = parts[1].Split('-')[0];
                return $"1.{major}.{minor}";
            }
            if (major == 47)
            {
                return "1.20.1";
            }
        }
        return null;
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
            return versions.Where(v => v.Stable).ToList();
        }

        return versions
            .Where(v => string.Equals(v.MinecraftVersion, minecraftVersion, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(v => v.Version, StringComparer.OrdinalIgnoreCase)
            .ToList();
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

    private static List<LoaderVersion> ParseMinecraftManifest(string json)
    {
        using var doc = JsonDocument.Parse(json);
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

        return list
            .OrderByDescending(v => VersionValue.TryParse(v.Version, out var val) ? val : VersionValue.Zero)
            .ToList();
    }

    private static IReadOnlyList<LoaderVersion> FilterMinecraftVersions(
        IReadOnlyList<LoaderVersion> versions,
        bool includeSnapshots) => includeSnapshots ? versions : versions.Where(v => v.Stable).ToList();

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
            string json = JsonCodec.Serialize(versions, indented: true);
            AtomicFileWriter.WriteText(cachePath, json);
        }
        catch
        {
        }
    }
}
