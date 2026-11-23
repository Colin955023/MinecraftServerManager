using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Loaders;

public sealed class MojangVersionCatalogTests : IDisposable
{
    private readonly TempDirectory _cacheDirTemp = new("msm-mojang-catalog-tests-");
    private readonly string _cacheDir;

    public MojangVersionCatalogTests()
    {
        _cacheDir = _cacheDirTemp.FullName;
    }

    public void Dispose() => _cacheDirTemp.Dispose();

    [Fact]
    public void ParseManifest_MixedEntries_FiltersServerJars()
    {
        const string manifest = """
        {
            "versions": [
                { "id": "1.21.4", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.4.json" },
                { "id": "1.2.4", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.2.4.json" },
                { "id": "24w05a", "type": "snapshot", "url": "https://piston-meta.mojang.com/v1/packages/test/24w05a.json" }
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
    public void TryGetCachedPackageUrl_CachedVersion_ReturnsUrl()
    {
        File.WriteAllText(
            MojangVersionCatalog.GetVersionsCachePath(_cacheDir),
            """[{ "Version": "1.20.4", "Url": "https://piston-meta.mojang.com/v1/packages/test/1.20.4.json", "Stable": true }]""");

        Assert.Equal("https://piston-meta.mojang.com/v1/packages/test/1.20.4.json", MojangVersionCatalog.TryGetCachedPackageUrl(_cacheDir, "1.20.4"));
        Assert.Null(MojangVersionCatalog.TryGetCachedPackageUrl(_cacheDir, "1.19.2"));
        Assert.Equal("https://piston-meta.mojang.com/v1/packages/test/1.20.4.json", MojangVersionCatalog.GetCachedReleasePackageUrls(_cacheDir)["1.20.4"]);
    }

    [Fact]
    public async Task FetchManifestAsync_PrimaryFails_UsesSecondaryUrl()
    {
        var http = new StubHttpPort(uri => uri.AbsoluteUri == MojangVersionCatalog.ManifestFallbackUrl
            ? """{ "versions": [ { "id": "1.20.1", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.20.1.json" } ] }"""
            : null);

        var versions = await MojangVersionCatalog.FetchManifestAsync(http, TestContext.Current.CancellationToken);

        Assert.NotNull(versions);
        Assert.Single(versions);
        Assert.Equal(2, http.RequestCount);
    }

    [Fact]
    public async Task FetchOfficialJavaMajorAsync_UnofficialPackageUrl_Rejects()
    {
        var http = new StubHttpPort(static _ => """{ "javaVersion": { "majorVersion": 21 } }""");

        int? major = await MojangVersionCatalog.FetchOfficialJavaMajorAsync(http, "https://example.com/1.21.4.json", TestContext.Current.CancellationToken);

        Assert.Null(major);
        Assert.Equal(0, http.RequestCount);
    }
}
