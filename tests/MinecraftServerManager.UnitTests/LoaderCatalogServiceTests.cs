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

    private sealed class FakeCatalogHttpPort(string responseText) : IHttpPort
    {
        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default) =>
            Task.FromResult<string?>(responseText);

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
