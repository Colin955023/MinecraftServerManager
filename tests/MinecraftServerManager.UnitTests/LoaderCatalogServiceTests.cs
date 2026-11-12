using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed partial class LoaderCatalogServiceTests : IDisposable
{
    private readonly TempDirectory _cacheDirTemp = new("msm-catalog-tests-");
    private readonly string _cacheDir;

    public LoaderCatalogServiceTests()
    {
        _cacheDir = _cacheDirTemp.FullName;
    }

    public void Dispose() => _cacheDirTemp.Dispose();

    [Fact]
    public async Task GetMinecraftVersionsAsyncParsesReleasesAndSnapshotsCorrectly()
    {
        string manifestJson = """
        {
            "versions": [
                { "id": "1.20.4", "type": "release", "url": "https://example.com/1.20.4.json" },
                { "id": "24w05a", "type": "snapshot", "url": "https://example.com/24w05a.json" }
            ]
        }
        """;

        var fakeHttp = new StubHttpPort(manifestJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var releasesOnly = await service.GetMinecraftVersionsAsync(includeSnapshots: false);
        var item = Assert.Single(releasesOnly);
        Assert.Equal("1.20.4", item.Version);
        Assert.True(item.Stable);

        var allVersions = await service.GetMinecraftVersionsAsync(includeSnapshots: true);
        Assert.Equal(2, allVersions.Count);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncFallsBackToStaleCacheWhenRemoteReturnsNothing()
    {
        var online = new LoaderCatalogService(new StubHttpPort("""[{ "version": "0.15.7", "stable": true }]"""), _cacheDir);
        Assert.Single(await online.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4"));

        string cacheFile = Path.Combine(_cacheDir, "fabric_versions_cache.json");
        File.SetLastWriteTimeUtc(cacheFile, DateTime.UtcNow.AddDays(-30));

        // 網路失敗時 IHttpPort 回傳失敗結果（此處為 null 文字）而非擲出
        var offline = new LoaderCatalogService(new StubHttpPort((string?)null), _cacheDir);
        var versions = await offline.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4");

        Assert.Equal("0.15.7", Assert.Single(versions).Version);
    }

    [Fact]
    public async Task GetPaperMinecraftVersionsFallsBackToStaleCacheWhenRemoteReturnsNothing()
    {
        var online = new LoaderCatalogService(new StubHttpPort(uri =>
        {
            string url = uri.AbsoluteUri;
            if (url.EndsWith("/projects/paper", StringComparison.OrdinalIgnoreCase))
            {
                return """{ "versions": { "1.21": [ "1.21.4" ] } }""";
            }

            return url.Contains("/builds", StringComparison.Ordinal)
                ? """[{"id": 100, "channel": "STABLE"}]"""
                : """{"version": {"java": {"version": {"minimum": 21}}}}""";
        }), _cacheDir);
        Assert.Single(await online.GetPaperMinecraftVersionsAsync());

        string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");
        File.SetLastWriteTimeUtc(cacheFile, DateTime.UtcNow.AddDays(-30));

        var offline = new LoaderCatalogService(new StubHttpPort((string?)null), _cacheDir);
        var versions = await offline.GetPaperMinecraftVersionsAsync();

        Assert.Equal("1.21.4", Assert.Single(versions).Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForFabricFiltersStableVersions()
    {
        string fabricJson = """
        [
            { "version": "0.15.7", "stable": true },
            { "version": "0.15.8-beta.1", "stable": false }
        ]
        """;

        var fakeHttp = new StubHttpPort(fabricJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4");
        var item = Assert.Single(versions);
        Assert.Equal("0.15.7", item.Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForForgeMapsMinecraftVersion()
    {
        string forgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>1.20.1-47.2.0</version>
                    <version>1.20.4-49.0.1</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var fakeHttp = new StubHttpPort(forgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.4");
        var item = Assert.Single(versions);
        Assert.Equal("49.0.1", item.Version);
        Assert.Equal("1.20.4", item.MinecraftVersion);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForForgeSortsBySemanticVersion()
    {
        string forgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>1.20.1-47.9.0</version>
                    <version>1.20.1-47.10.0</version>
                    <version>1.20.1-47.2.0</version>
                    <version>1.20.1-47.11.1</version>
                    <version>1.20.1-47.1.0</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var service = new LoaderCatalogService(new StubHttpPort(forgeXml), _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.1");
        Assert.Equal(["47.11.1", "47.10.0", "47.9.0", "47.2.0"], versions.Select(static v => v.Version));
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForNeoForgeDerivesMinecraftVersion()
    {
        string neoForgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>20.4.80</version>
                    <version>20.4.81-beta</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var fakeHttp = new StubHttpPort(neoForgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "1.20.4");
        Assert.Equal(2, versions.Count);
        Assert.Equal("20.4.81-beta", versions[0].Version);
        Assert.False(versions[0].Stable);
        Assert.Equal("20.4.80", versions[1].Version);
        Assert.True(versions[1].Stable);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForNeoForgeFromMinecraft26ReturnsVersionsWithPrefixedMinecraftVersion()
    {
        string neoForgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>26.3.0.10-beta</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var fakeHttp = new StubHttpPort(neoForgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        // 使用者查詢 26.3，統一規則解析為 26.3，應能成功比對
        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.3");
        var item = Assert.Single(versions);
        Assert.Equal("26.3.0.10-beta", item.Version);
        Assert.Equal("26.3", item.MinecraftVersion);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForFabricKeepsOnlyLatestStableReleaseVersion()
    {
        string fabricJson = """
        [
            { "version": "0.16.1", "stable": true },
            { "version": "0.16.0", "stable": true },
            { "version": "0.15.9-beta.2", "stable": true },
            { "version": "0.15.8", "stable": true }
        ]
        """;

        var fakeHttp = new StubHttpPort(fabricJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4");
        var item = Assert.Single(versions);
        Assert.Equal("0.16.1", item.Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForForgeKeepsAtMostFourVersionsAndFiltersPrereleases()
    {
        string forgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>1.20.4-49.0.1</version>
                    <version>1.20.4-49.0.2</version>
                    <version>1.20.4-49.0.3-beta.1</version>
                    <version>1.20.4-49.0.4</version>
                    <version>1.20.4-49.0.5</version>
                    <version>1.20.4-49.0.6</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var fakeHttp = new StubHttpPort(forgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.4");
        Assert.Equal(4, versions.Count);
        Assert.Equal("49.0.6", versions[0].Version);
        Assert.Equal("49.0.5", versions[1].Version);
        Assert.Equal("49.0.4", versions[2].Version);
        Assert.Equal("49.0.2", versions[3].Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForNeoForgeSortsFourSegmentVersionsNumerically()
    {
        string neoForgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>26.3.0.79</version>
                    <version>26.3.0.101</version>
                    <version>26.3.0.9</version>
                    <version>26.3.0.99</version>
                    <version>26.3.0.100</version>
                    <version>26.3.0.80</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var service = new LoaderCatalogService(new StubHttpPort(neoForgeXml), _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.3");
        Assert.Equal(["26.3.0.101", "26.3.0.100", "26.3.0.99", "26.3.0.80"], versions.Select(static v => v.Version));
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForNeoForgeSeparatesMinecraftHotfixReleases()
    {
        string neoForgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>26.1.0.5</version>
                    <version>26.1.2.36-beta</version>
                    <version>26.1.2.126</version>
                    <version>26.1.1.14</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var service = new LoaderCatalogService(new StubHttpPort(neoForgeXml), _cacheDir);

        var hotfix = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.1.2");
        Assert.Equal(["26.1.2.126", "26.1.2.36-beta"], hotfix.Select(static v => v.Version));
        Assert.All(hotfix, static v => Assert.Equal("26.1.2", v.MinecraftVersion));

        var baseRelease = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.1");
        Assert.Equal("26.1.0.5", Assert.Single(baseRelease).Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForNeoForgeKeepsAtMostFourVersionsWithoutFilteringBeta()
    {
        string neoForgeXml = """
        <metadata>
            <versioning>
                <versions>
                    <version>20.4.80</version>
                    <version>20.4.81-beta</version>
                    <version>20.4.82-beta</version>
                    <version>20.4.83-beta</version>
                    <version>20.4.84-beta</version>
                    <version>20.4.85-beta</version>
                </versions>
            </versioning>
        </metadata>
        """;

        var fakeHttp = new StubHttpPort(neoForgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "1.20.4");
        Assert.Equal(4, versions.Count);
        Assert.Equal("20.4.85-beta", versions[0].Version);
        Assert.Equal("20.4.84-beta", versions[1].Version);
        Assert.Equal("20.4.83-beta", versions[2].Version);
        Assert.Equal("20.4.82-beta", versions[3].Version);
    }

    [Fact]
    public async Task GetPaperMinecraftVersionsParsesAndSortsVersionsCorrectly()
    {
        string paperProjectJson = """
        {
            "project": { "id": "paper", "name": "Paper" },
            "versions": {
                "1.21": [ "1.21", "1.21.1", "1.21.4", "1.21-pre1" ],
                "1.20": [ "1.20.1", "1.20.6", "24w05a" ]
            }
        }
        """;

        var fakeHttp = new StubHttpPort(uri =>
        {
            string url = uri.AbsoluteUri;
            if (url.EndsWith("/projects/paper", StringComparison.OrdinalIgnoreCase))
            {
                return paperProjectJson;
            }
            if (url.Contains("/builds"))
            {
                return """[{"id": 100, "channel": "STABLE"}]""";
            }
            if (url.Contains("/versions/1.21.4"))
            {
                return """{"version": {"java": {"version": {"minimum": 21}}}}""";
            }
            if (url.Contains("/versions/1.20.1"))
            {
                return """{"version": {"java": {"version": {"minimum": 17}}}}""";
            }
            return """{"version": {"java": {"version": {"minimum": 17}}}}""";
        });

        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Paper);
        Assert.Equal(5, versions.Count);
        Assert.Equal("1.21.4", versions[0].Version);
        Assert.Equal(21, versions[0].JavaMajor);
        Assert.Equal("1.21.1", versions[1].Version);
        Assert.Equal("1.20.1", versions[4].Version);
        Assert.Equal(17, versions[4].JavaMajor);
        Assert.DoesNotContain(versions, v => v.Version.Contains('-') || v.Version.Contains('w'));

        string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");
        Assert.True(File.Exists(cacheFile));

        int reqBefore = fakeHttp.RequestCount;
        var cachedVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Paper);
        Assert.Equal(5, cachedVersions.Count);
        Assert.Equal(reqBefore, fakeHttp.RequestCount);
        Assert.Equal(21, cachedVersions[0].JavaMajor);
    }

    [Fact]
    public async Task GetLoaderVersionsAsyncForPaperParsesBuildsAndDownloads()
    {
        string buildsJson = """
        [
            {
                "id": 164,
                "channel": "STABLE",
                "downloads": {
                    "server:application": {
                        "name": "paper-1.21.4-164.jar",
                        "url": "https://fill-data.papermc.io/paper-1.21.4-164.jar"
                    }
                }
            },
            {
                "id": 165,
                "channel": "STABLE",
                "downloads": {
                    "server:application": {
                        "name": "paper-1.21.4-165.jar",
                        "url": "https://fill-data.papermc.io/paper-1.21.4-165.jar"
                    }
                }
            }
        ]
        """;

        var fakeHttp = new StubHttpPort(buildsJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var builds = await service.GetLoaderVersionsAsync(LoaderKind.Paper, "1.21.4");
        // Paper 載入器版本應只取最新版本 (Latest Build)
        var item = Assert.Single(builds);
        Assert.Equal("165", item.Version);
        Assert.True(item.Stable);
        Assert.Equal("https://fill-data.papermc.io/paper-1.21.4-165.jar", item.Url);
    }

    [Fact]
    public async Task ReloadAndMergeMinecraftVersionsAsyncShouldFetchJavaMajorForNewOfficialVersions()
    {
        string manifestJson = """
        {
            "versions": [
                {
                    "id": "1.21.4",
                    "type": "release",
                    "url": "https://piston-meta.mojang.com/v1/packages/pkg-1.21.4.json"
                }
            ]
        }
        """;

        string packageJson = """
        {
            "id": "1.21.4",
            "javaVersion": {
                "component": "java-runtime-gamma",
                "majorVersion": 21
            },
            "downloads": {
                "server": {
                    "url": "https://piston-data.mojang.com/server.jar"
                }
            }
        }
        """;

        var fakeHttp = new StubHttpPort(uri =>
        {
            if (uri.ToString().Contains("version_manifest.json"))
            {
                return manifestJson;
            }
            if (uri.ToString().Contains("pkg-1.21.4.json"))
            {
                return packageJson;
            }
            return null;
        });

        var service = new LoaderCatalogService(fakeHttp, _cacheDir);
        var versions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Fabric, forceReload: true);

        Assert.NotEmpty(versions);
        var v = Assert.Single(versions);
        Assert.Equal("1.21.4", v.Version);
        Assert.Equal(21, v.JavaMajor);

        string mcCache = Path.Combine(_cacheDir, "mc_versions_cache.json");
        Assert.True(File.Exists(mcCache));
        string mcContent = await File.ReadAllTextAsync(mcCache);
        Assert.Contains("\"JavaMajor\": 21", mcContent);
    }

    [Fact]
    public async Task GetMinecraftVersionsForLoaderAsync_ForFabricAndQuilt_FiltersOutVersionsLessThan1_14()
    {
        string manifestJson = """
        {
            "versions": [
                { "id": "1.20.4", "type": "release", "url": "https://example.com/1.20.4.json" },
                { "id": "1.14", "type": "release", "url": "https://example.com/1.14.json" },
                { "id": "1.13.2", "type": "release", "url": "https://example.com/1.13.2.json" },
                { "id": "1.12.2", "type": "release", "url": "https://example.com/1.12.2.json" }
            ]
        }
        """;

        var fakeHttp = new StubHttpPort(manifestJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var fabricVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Fabric);
        Assert.Equal(2, fabricVersions.Count);
        Assert.Contains(fabricVersions, static v => v.Version == "1.20.4");
        Assert.Contains(fabricVersions, static v => v.Version == "1.14");
        Assert.DoesNotContain(fabricVersions, static v => v.Version == "1.13.2");
        Assert.DoesNotContain(fabricVersions, static v => v.Version == "1.12.2");

        var quiltVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Quilt);
        Assert.Equal(2, quiltVersions.Count);
        Assert.Contains(quiltVersions, static v => v.Version == "1.20.4");
        Assert.Contains(quiltVersions, static v => v.Version == "1.14");
        Assert.DoesNotContain(quiltVersions, static v => v.Version == "1.13.2");
        Assert.DoesNotContain(quiltVersions, static v => v.Version == "1.12.2");
    }

    [Fact]
    public async Task GetPaperMinecraftVersionsAsync_ExcludesVersionsWithoutStableBuilds()
    {
        string projectJson = """
        {
            "versions": {
                "1.21": ["1.21.4"],
                "26": ["26.3"]
            }
        }
        """;

        string builds263Json = """
        [
            { "id": 1, "channel": "BETA" },
            { "id": 2, "channel": "ALPHA" }
        ]
        """;

        string builds1214Json = """
        [
            { "id": 165, "channel": "STABLE" }
        ]
        """;

        string version1214Json = """
        {
            "version": {
                "java": {
                    "version": {
                        "minimum": 21
                    }
                }
            }
        }
        """;

        var fakeHttp = new StubHttpPort(uri =>
        {
            string s = uri.ToString();
            if (s.EndsWith("/projects/paper", StringComparison.OrdinalIgnoreCase))
            {
                return projectJson;
            }
            if (s.Contains("/versions/26.3/builds"))
            {
                return builds263Json;
            }
            if (s.Contains("/versions/1.21.4/builds"))
            {
                return builds1214Json;
            }
            if (s.Contains("/versions/1.21.4"))
            {
                return version1214Json;
            }
            return null;
        });

        var service = new LoaderCatalogService(fakeHttp, _cacheDir);
        var paperVersions = await service.GetPaperMinecraftVersionsAsync(forceReload: true);

        // 26.3 僅有 BETA/ALPHA，無任何 STABLE 建置，必須被剔除！
        var item = Assert.Single(paperVersions);
        Assert.Equal("1.21.4", item.Version);
        Assert.Equal("165", item.Build);
        Assert.Equal(21, item.JavaMajor);
    }

    [Fact]
    public async Task GetMinecraftVersionsAsync_CleansCacheFileOfUnstableEntries()
    {
        string cacheFile = Path.Combine(_cacheDir, "mc_versions_cache.json");
        string dirtyCacheJson = """
        [
            { "Version": "1.20.4", "Url": "https://example.com/1.20.4.json", "Stable": true },
            { "Version": "24w05a", "Url": "https://example.com/24w05a.json", "Stable": false }
        ]
        """;
        await File.WriteAllTextAsync(cacheFile, dirtyCacheJson);

        var fakeHttp = new StubHttpPort("");
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetMinecraftVersionsAsync(includeSnapshots: false);

        var item = Assert.Single(versions);
        Assert.Equal("1.20.4", item.Version);

        string cleanedJson = await File.ReadAllTextAsync(cacheFile);
        Assert.DoesNotContain("24w05a", cleanedJson);
    }

    [Fact]
    public void MojangVersionCatalogParsesManifestAndFiltersServerJars()
    {
        const string manifest = """
        {
            "versions": [
                { "id": "1.21.4", "type": "release", "url": "https://example.com/1.21.4.json" },
                { "id": "1.2.4", "type": "release", "url": "https://example.com/1.2.4.json" },
                { "id": "24w05a", "type": "snapshot", "url": "https://example.com/24w05a.json" }
            ]
        }
        """;

        using var doc = JsonCodec.ParseDocument(manifest);
        var versions = MojangVersionCatalog.ParseManifest(doc);

        Assert.Contains(versions, static v => v.Version == "1.21.4" && v.Stable);
        Assert.Contains(versions, static v => v.Version == "24w05a" && !v.Stable);
        Assert.DoesNotContain(versions, static v => v.Version == "1.2.4");
    }

    [Fact]
    public void MojangVersionCatalogFindsCachedPackageUrl()
    {
        File.WriteAllText(
            MojangVersionCatalog.GetVersionsCachePath(_cacheDir),
            """[{ "Version": "1.20.4", "Url": "https://example.com/1.20.4.json", "Stable": true }]""");

        Assert.Equal("https://example.com/1.20.4.json", MojangVersionCatalog.TryGetCachedPackageUrl(_cacheDir, "1.20.4"));
        Assert.Null(MojangVersionCatalog.TryGetCachedPackageUrl(_cacheDir, "1.19.2"));
        Assert.Equal("https://example.com/1.20.4.json", MojangVersionCatalog.GetCachedReleasePackageUrls(_cacheDir)["1.20.4"]);
    }

    [Fact]
    public async Task MojangVersionCatalogFallsBackToSecondaryManifestUrl()
    {
        var http = new StubHttpPort(uri => uri.AbsoluteUri == MojangVersionCatalog.ManifestFallbackUrl
            ? """{ "versions": [ { "id": "1.20.1", "type": "release", "url": "https://example.com/1.20.1.json" } ] }"""
            : null);

        var versions = await MojangVersionCatalog.FetchManifestAsync(http, CancellationToken.None);

        Assert.NotNull(versions);
        Assert.Single(versions);
        Assert.Equal(2, http.RequestCount);
    }

    [Fact]
    public async Task MojangVersionCatalogAppliesJavaFloorForPaper()
    {
        var http = new StubHttpPort(static _ => """{ "version": { "java": { "version": { "minimum": 7 } } } }""");

        int? major = await MojangVersionCatalog.FetchPaperJavaMajorAsync(http, "1.8.8", CancellationToken.None);

        Assert.Equal(MojangVersionCatalog.MinimumJavaMajor, major);
    }
}
