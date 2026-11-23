using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Loaders;

namespace MinecraftServerManager.UnitTests.Loaders;

public sealed class LoaderCatalogServiceTests : IDisposable
{
    private readonly TempDirectory _cacheDirTemp = new("msm-catalog-tests-");
    private readonly string _cacheDir;

    public LoaderCatalogServiceTests()
    {
        _cacheDir = _cacheDirTemp.FullName;
    }

    public void Dispose() => _cacheDirTemp.Dispose();

    private LoaderCatalogService CreateService(IHttpPort http) => new(http, _cacheDir, TimeProvider.System);

    private static string MavenVersionsXml(params string[] versions) =>
        $"""
        <metadata>
            <versioning>
                <versions>
                    {string.Join("\n", versions.Select(static v => $"<version>{v}</version>"))}
                </versions>
            </versioning>
        </metadata>
        """;

    /// <summary>Mojang 官方 Manifest 與版本 JSON 替身；Paper 的 Java major 亦取自此</summary>
    private static string? MojangStub(string url, params (string Id, int JavaMajor)[] versions)
    {
        if (url.Contains("version_manifest", StringComparison.Ordinal))
        {
            string entries = string.Join(",", versions.Select(static v =>
                $$"""{ "id": "{{v.Id}}", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/{{v.Id}}.json" }"""));
            return $$"""{ "versions": [ {{entries}} ] }""";
        }

        foreach (var (id, major) in versions)
        {
            if (url.EndsWith($"/test/{id}.json", StringComparison.Ordinal))
            {
                return $$"""{ "javaVersion": { "majorVersion": {{major}} } }""";
            }
        }

        return null;
    }

    [Fact]
    public async Task GetMinecraftVersionsAsync_Manifest_ParsesReleasesAndSnapshots()
    {
        string manifestJson = """
        {
            "versions": [
                { "id": "1.20.4", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.20.4.json" },
                { "id": "24w05a", "type": "snapshot", "url": "https://piston-meta.mojang.com/v1/packages/test/24w05a.json" }
            ]
        }
        """;

        var service = CreateService(new StubHttpPort(manifestJson));

        var releasesOnly = await service.GetMinecraftVersionsAsync(includeSnapshots: false, cancellationToken: TestContext.Current.CancellationToken);
        var item = Assert.Single(releasesOnly);
        Assert.Equal("1.20.4", item.Version);
        Assert.True(item.Stable);

        var allVersions = await service.GetMinecraftVersionsAsync(includeSnapshots: true, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(2, allVersions.Count);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_RemoteEmpty_FallsBackToStaleCache()
    {
        var online = CreateService(new StubHttpPort("""[{ "version": "0.15.7", "stable": true }]"""));
        Assert.Single(await online.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4", TestContext.Current.CancellationToken));

        string cacheFile = Path.Combine(_cacheDir, "fabric_versions_cache.json");
        File.SetLastWriteTimeUtc(cacheFile, DateTime.UtcNow.AddDays(-30));

        // 網路失敗時 IHttpPort 回傳失敗結果（此處為 null 文字）而非擲出
        var offline = CreateService(new StubHttpPort((string?)null));
        var versions = await offline.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4", TestContext.Current.CancellationToken);

        Assert.Equal("0.15.7", Assert.Single(versions).Version);
    }

    [Fact]
    public async Task GetPaperMinecraftVersions_RemoteEmpty_FallsBackToStaleCache()
    {
        var online = CreateService(new StubHttpPort(uri =>
        {
            string url = uri.AbsoluteUri;
            if (url.EndsWith("/projects/paper", StringComparison.OrdinalIgnoreCase))
            {
                return """{ "versions": { "1.21": [ "1.21.4" ] } }""";
            }

            return url.Contains("/builds", StringComparison.Ordinal)
                ? """[{"id": 100, "channel": "STABLE"}]"""
                : MojangStub(url, ("1.21.4", 21));
        }));
        Assert.Single(await online.GetPaperMinecraftVersionsAsync(cancellationToken: TestContext.Current.CancellationToken));

        string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");
        File.SetLastWriteTimeUtc(cacheFile, DateTime.UtcNow.AddDays(-30));

        var offline = CreateService(new StubHttpPort((string?)null));
        var versions = await offline.GetPaperMinecraftVersionsAsync(cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal("1.21.4", Assert.Single(versions).Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_Fabric_FiltersStableVersions()
    {
        string fabricJson = """
        [
            { "version": "0.15.7", "stable": true },
            { "version": "0.15.8-beta.1", "stable": false }
        ]
        """;

        var service = CreateService(new StubHttpPort(fabricJson));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4", TestContext.Current.CancellationToken);
        var item = Assert.Single(versions);
        Assert.Equal("0.15.7", item.Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_Forge_MapsMinecraftVersion()
    {
        string forgeXml = MavenVersionsXml("1.20.1-47.2.0", "1.20.4-49.0.1");
        var service = CreateService(new StubHttpPort(forgeXml));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.4", TestContext.Current.CancellationToken);
        var item = Assert.Single(versions);
        Assert.Equal("49.0.1", item.Version);
        Assert.Equal("1.20.4", item.MinecraftVersion);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_Forge_SortsBySemanticVersion()
    {
        string forgeXml = MavenVersionsXml(
            "1.20.1-47.9.0",
            "1.20.1-47.10.0",
            "1.20.1-47.2.0",
            "1.20.1-47.11.1",
            "1.20.1-47.1.0");

        var service = CreateService(new StubHttpPort(forgeXml));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.1", TestContext.Current.CancellationToken);
        Assert.Equal(["47.11.1", "47.10.0", "47.9.0", "47.2.0"], versions.Select(static v => v.Version));
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_NeoForge_DerivesMinecraftVersion()
    {
        string neoForgeXml = MavenVersionsXml("20.4.80", "20.4.81-beta");
        var service = CreateService(new StubHttpPort(neoForgeXml));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "1.20.4", TestContext.Current.CancellationToken);
        Assert.Equal(2, versions.Count);
        Assert.Equal("20.4.81-beta", versions[0].Version);
        Assert.False(versions[0].Stable);
        Assert.Equal("20.4.80", versions[1].Version);
        Assert.True(versions[1].Stable);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_NeoForgeMinecraft26_UsesPrefixedMinecraftVersion()
    {
        string neoForgeXml = MavenVersionsXml("26.3.0.10-beta");
        var service = CreateService(new StubHttpPort(neoForgeXml));

        // 使用者查詢 26.3，統一規則解析為 26.3，應能成功比對
        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.3", TestContext.Current.CancellationToken);
        var item = Assert.Single(versions);
        Assert.Equal("26.3.0.10-beta", item.Version);
        Assert.Equal("26.3", item.MinecraftVersion);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_FabricMultipleStable_KeepsLatestOnly()
    {
        string fabricJson = """
        [
            { "version": "0.16.1", "stable": true },
            { "version": "0.16.0", "stable": true },
            { "version": "0.15.9-beta.2", "stable": true },
            { "version": "0.15.8", "stable": true }
        ]
        """;

        var service = CreateService(new StubHttpPort(fabricJson));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4", TestContext.Current.CancellationToken);
        var item = Assert.Single(versions);
        Assert.Equal("0.16.1", item.Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_ForgeManyVersions_KeepsFourStable()
    {
        string forgeXml = MavenVersionsXml(
            "1.20.4-49.0.1",
            "1.20.4-49.0.2",
            "1.20.4-49.0.3-beta.1",
            "1.20.4-49.0.4",
            "1.20.4-49.0.5",
            "1.20.4-49.0.6");

        var service = CreateService(new StubHttpPort(forgeXml));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.4", TestContext.Current.CancellationToken);
        Assert.Equal(4, versions.Count);
        Assert.Equal("49.0.6", versions[0].Version);
        Assert.Equal("49.0.5", versions[1].Version);
        Assert.Equal("49.0.4", versions[2].Version);
        Assert.Equal("49.0.2", versions[3].Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_NeoForgeFourSegments_SortsNumerically()
    {
        string neoForgeXml = MavenVersionsXml(
            "26.3.0.79",
            "26.3.0.101",
            "26.3.0.9",
            "26.3.0.99",
            "26.3.0.100",
            "26.3.0.80");

        var service = CreateService(new StubHttpPort(neoForgeXml));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.3", TestContext.Current.CancellationToken);
        Assert.Equal(["26.3.0.101", "26.3.0.100", "26.3.0.99", "26.3.0.80"], versions.Select(static v => v.Version));
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_NeoForgeHotfix_SeparatesMinecraftVersions()
    {
        string neoForgeXml = MavenVersionsXml(
            "26.1.0.5",
            "26.1.2.36-beta",
            "26.1.2.126",
            "26.1.1.14");

        var service = CreateService(new StubHttpPort(neoForgeXml));

        var hotfix = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.1.2", TestContext.Current.CancellationToken);
        Assert.Equal(["26.1.2.126", "26.1.2.36-beta"], hotfix.Select(static v => v.Version));
        Assert.All(hotfix, static v => Assert.Equal("26.1.2", v.MinecraftVersion));

        var baseRelease = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.1", TestContext.Current.CancellationToken);
        Assert.Equal("26.1.0.5", Assert.Single(baseRelease).Version);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_NeoForgeManyVersions_KeepsFourIncludingBeta()
    {
        string neoForgeXml = MavenVersionsXml(
            "20.4.80",
            "20.4.81-beta",
            "20.4.82-beta",
            "20.4.83-beta",
            "20.4.84-beta",
            "20.4.85-beta");

        var service = CreateService(new StubHttpPort(neoForgeXml));

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "1.20.4", TestContext.Current.CancellationToken);
        Assert.Equal(4, versions.Count);
        Assert.Equal("20.4.85-beta", versions[0].Version);
        Assert.Equal("20.4.84-beta", versions[1].Version);
        Assert.Equal("20.4.83-beta", versions[2].Version);
        Assert.Equal("20.4.82-beta", versions[3].Version);
    }

    [Fact]
    public async Task GetPaperMinecraftVersions_RemoteList_ParsesAndSorts()
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
            if (url.Contains("version_manifest"))
            {
                return """
                {
                    "versions": [
                        { "id": "1.21.4", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.4.json" },
                        { "id": "1.21.1", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.1.json" },
                        { "id": "1.21", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.json" },
                        { "id": "1.20.6", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.20.6.json" },
                        { "id": "1.20.1", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.20.1.json" }
                    ]
                }
                """;
            }
            // Paper 的 Java major 依 Mojang 官方版本 JSON，而非 Paper API
            return url.Contains("/test/1.21")
                ? """{"javaVersion": {"majorVersion": 21}}"""
                : """{"javaVersion": {"majorVersion": 17}}""";
        });

        var service = CreateService(fakeHttp);

        var versions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Paper, cancellationToken: TestContext.Current.CancellationToken);
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
        var cachedVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Paper, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(5, cachedVersions.Count);
        Assert.Equal(reqBefore, fakeHttp.RequestCount);
        Assert.Equal(21, cachedVersions[0].JavaMajor);
    }

    [Fact]
    public async Task GetLoaderVersionsAsync_Paper_ParsesBuildsAndDownloads()
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

        var service = CreateService(new StubHttpPort(buildsJson));

        var builds = await service.GetLoaderVersionsAsync(LoaderKind.Paper, "1.21.4", TestContext.Current.CancellationToken);
        // Paper 載入器版本應只取最新版本 (Latest Build)
        var item = Assert.Single(builds);
        Assert.Equal("165", item.Version);
        Assert.True(item.Stable);
        Assert.Equal("https://fill-data.papermc.io/paper-1.21.4-165.jar", item.Url);
    }

    [Fact]
    public async Task ReloadAndMergeMinecraftVersionsAsync_NewOfficialVersion_FetchesJavaMajor()
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

        var service = CreateService(new StubHttpPort(uri =>
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
        }));
        var versions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Fabric, forceReload: true, cancellationToken: TestContext.Current.CancellationToken);

        Assert.NotEmpty(versions);
        var v = Assert.Single(versions);
        Assert.Equal("1.21.4", v.Version);
        Assert.Equal(21, v.JavaMajor);

        string mcCache = Path.Combine(_cacheDir, "mc_versions_cache.json");
        Assert.True(File.Exists(mcCache));
        string mcContent = await File.ReadAllTextAsync(mcCache, TestContext.Current.CancellationToken);
        Assert.Contains("\"JavaMajor\": 21", mcContent);
    }

    [Fact]
    public async Task GetMinecraftVersionsForLoaderAsync_ForFabricAndQuilt_FiltersOutVersionsLessThan1_14()
    {
        string manifestJson = """
        {
            "versions": [
                { "id": "1.20.4", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.20.4.json" },
                { "id": "1.14", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.14.json" },
                { "id": "1.13.2", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.13.2.json" },
                { "id": "1.12.2", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.12.2.json" }
            ]
        }
        """;

        var service = CreateService(new StubHttpPort(manifestJson));

        var fabricVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Fabric, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(2, fabricVersions.Count);
        Assert.Contains(fabricVersions, static v => v.Version == "1.20.4");
        Assert.Contains(fabricVersions, static v => v.Version == "1.14");
        Assert.DoesNotContain(fabricVersions, static v => v.Version == "1.13.2");
        Assert.DoesNotContain(fabricVersions, static v => v.Version == "1.12.2");

        var quiltVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Quilt, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(2, quiltVersions.Count);
        Assert.Contains(quiltVersions, static v => v.Version == "1.20.4");
        Assert.Contains(quiltVersions, static v => v.Version == "1.14");
        Assert.DoesNotContain(quiltVersions, static v => v.Version == "1.13.2");
        Assert.DoesNotContain(quiltVersions, static v => v.Version == "1.12.2");
    }

    [Fact]
    public async Task GetPaperMinecraftVersionsAsync_NoStableBuild_ExcludesVersion()
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

        var service = CreateService(new StubHttpPort(uri =>
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
            return MojangStub(s, ("1.21.4", 21));
        }));
        var paperVersions = await service.GetPaperMinecraftVersionsAsync(forceReload: true, cancellationToken: TestContext.Current.CancellationToken);

        // 26.3 僅有 BETA/ALPHA，無任何 STABLE 建置，必須被剔除！
        var item = Assert.Single(paperVersions);
        Assert.Equal("1.21.4", item.Version);
        Assert.Equal("165", item.Build);
        Assert.Equal(21, item.JavaMajor);
    }

    [Fact]
    public async Task GetMinecraftVersionsAsync_UnstableCacheEntries_CleansCache()
    {
        string cacheFile = Path.Combine(_cacheDir, "mc_versions_cache.json");
        string dirtyCacheJson = """
        [
            { "Version": "1.20.4", "Url": "https://piston-meta.mojang.com/v1/packages/test/1.20.4.json", "Stable": true },
            { "Version": "24w05a", "Url": "https://piston-meta.mojang.com/v1/packages/test/24w05a.json", "Stable": false }
        ]
        """;
        await File.WriteAllTextAsync(cacheFile, dirtyCacheJson, TestContext.Current.CancellationToken);

        var service = CreateService(new StubHttpPort(""));

        var versions = await service.GetMinecraftVersionsAsync(includeSnapshots: false, cancellationToken: TestContext.Current.CancellationToken);

        var item = Assert.Single(versions);
        Assert.Equal("1.20.4", item.Version);

        string cleanedJson = await File.ReadAllTextAsync(cacheFile, TestContext.Current.CancellationToken);
        Assert.DoesNotContain("24w05a", cleanedJson);
    }
}
