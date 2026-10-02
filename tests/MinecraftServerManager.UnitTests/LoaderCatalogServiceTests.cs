using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Loaders;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class LoaderCatalogServiceTests : IDisposable
{
    private readonly string _cacheDir;

    public LoaderCatalogServiceTests()
    {
        _cacheDir = Path.Combine(Path.GetTempPath(), "msm-catalog-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_cacheDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_cacheDir))
            {
                Directory.Delete(_cacheDir, recursive: true);
            }
        }
        catch
        {
        }
    }

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

        var fakeHttp = new FakeCatalogHttpPort(manifestJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var releasesOnly = await service.GetMinecraftVersionsAsync(includeSnapshots: false);
        Assert.Single(releasesOnly);
        Assert.Equal("1.20.4", releasesOnly[0].Version);
        Assert.True(releasesOnly[0].Stable);

        var allVersions = await service.GetMinecraftVersionsAsync(includeSnapshots: true);
        Assert.Equal(2, allVersions.Count);
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

        var fakeHttp = new FakeCatalogHttpPort(fabricJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4");
        Assert.Single(versions);
        Assert.Equal("0.15.7", versions[0].Version);
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

        var fakeHttp = new FakeCatalogHttpPort(forgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.4");
        Assert.Single(versions);
        Assert.Equal("49.0.1", versions[0].Version);
        Assert.Equal("1.20.4", versions[0].MinecraftVersion);
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

        var fakeHttp = new FakeCatalogHttpPort(neoForgeXml);
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

        var fakeHttp = new FakeCatalogHttpPort(neoForgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        // 使用者查詢 26.3，快取解析為 1.26.3，應能成功比對
        var versions = await service.GetLoaderVersionsAsync(LoaderKind.NeoForge, "26.3");
        Assert.Single(versions);
        Assert.Equal("26.3.0.10-beta", versions[0].Version);
        Assert.Equal("1.26.3", versions[0].MinecraftVersion);
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

        var fakeHttp = new FakeCatalogHttpPort(fabricJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Fabric, "1.20.4");
        Assert.Single(versions);
        Assert.Equal("0.16.1", versions[0].Version);
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

        var fakeHttp = new FakeCatalogHttpPort(forgeXml);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var versions = await service.GetLoaderVersionsAsync(LoaderKind.Forge, "1.20.4");
        Assert.Equal(4, versions.Count);
        Assert.Equal("49.0.6", versions[0].Version);
        Assert.Equal("49.0.5", versions[1].Version);
        Assert.Equal("49.0.4", versions[2].Version);
        Assert.Equal("49.0.2", versions[3].Version);
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

        var fakeHttp = new FakeCatalogHttpPort(neoForgeXml);
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

        int requestCount = 0;
        var fakeHttp = new FakeCatalogHttpPort(uri =>
        {
            requestCount++;
            string url = uri.AbsoluteUri;
            if (url.EndsWith("/projects/paper", StringComparison.OrdinalIgnoreCase))
            {
                return paperProjectJson;
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
        // 應篩選排除 1.21-pre1 與 24w05a，僅保留 5 個正式發布版
        Assert.Equal(5, versions.Count);
        Assert.Equal("1.21.4", versions[0].Version);
        Assert.Equal(21, versions[0].JavaMajor);
        Assert.Equal("1.21.1", versions[1].Version);
        Assert.Equal("1.20.1", versions[4].Version);
        Assert.Equal(17, versions[4].JavaMajor);
        Assert.DoesNotContain(versions, v => v.Version.Contains('-') || v.Version.Contains('w'));

        // 驗證寫入 paper_mc_versions_cache.json
        string cacheFile = Path.Combine(_cacheDir, "paper_mc_versions_cache.json");
        Assert.True(File.Exists(cacheFile));

        // 第二次呼叫：直接從快取讀取，不發送額外網路請求
        int reqBefore = requestCount;
        var cachedVersions = await service.GetMinecraftVersionsForLoaderAsync(LoaderKind.Paper);
        Assert.Equal(5, cachedVersions.Count);
        Assert.Equal(reqBefore, requestCount);
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

        var fakeHttp = new FakeCatalogHttpPort(buildsJson);
        var service = new LoaderCatalogService(fakeHttp, _cacheDir);

        var builds = await service.GetLoaderVersionsAsync(LoaderKind.Paper, "1.21.4");
        // Paper 載入器版本應只取最新版本 (Latest Build)
        Assert.Single(builds);
        Assert.Equal("165", builds[0].Version);
        Assert.True(builds[0].Stable);
        Assert.Equal("https://fill-data.papermc.io/paper-1.21.4-165.jar", builds[0].Url);

        // 驗證不應在磁碟中寫入零碎的 build 快取檔案
        Assert.False(File.Exists(Path.Combine(_cacheDir, "paper_1.21.4_builds_cache.json")));
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

        var fakeHttp = new FakeCatalogHttpPort(uri =>
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
        string reqCache = Path.Combine(_cacheDir, "mc_java_requirements_cache.json");
        Assert.True(File.Exists(mcCache));
        Assert.True(File.Exists(reqCache));
        string reqContent = await File.ReadAllTextAsync(reqCache);
        Assert.Contains("\"1.21.4\": 21", reqContent);
    }

    private sealed class FakeCatalogHttpPort : IHttpPort
    {
        private readonly Func<Uri, string?> _handler;

        public FakeCatalogHttpPort(string responseText)
        {
            _handler = _ => responseText;
        }

        public FakeCatalogHttpPort(Func<Uri, string?> handler)
        {
            _handler = handler;
        }

        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default) =>
            Task.FromResult(_handler(uri));

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default) =>
            Task.FromResult(new HttpResult(true));

        public Task<string?> PostJsonAsync(
            Uri uri,
            string jsonPayload,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<string?>(null);
    }
}
