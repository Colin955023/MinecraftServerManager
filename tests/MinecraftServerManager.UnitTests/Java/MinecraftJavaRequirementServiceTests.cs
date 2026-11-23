using System.Text.Json;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Loaders;

namespace MinecraftServerManager.UnitTests.Java;

public sealed class MinecraftJavaRequirementServiceTests : IDisposable
{
    private readonly TempDirectory _testTempDirTemp = new("msm_java_req_test_");
    private readonly string _testTempDir;

    public MinecraftJavaRequirementServiceTests()
    {
        _testTempDir = _testTempDirTemp.FullName;
    }

    public void Dispose() => _testTempDirTemp.Dispose();

    [Fact]
    public void ParseJavaMajorFromVersionJson_StandardStructure_ReturnsMajor()
    {
        string json = """
        {
            "id": "1.21.4",
            "javaVersion": {
                "component": "java-runtime-gamma",
                "majorVersion": 21
            }
        }
        """;

        int? major = ParseMajor(json);
        Assert.Equal(21, major);
    }

    [Fact]
    public void ParseJavaMajorFromVersionJson_AlternativeStructure_ReturnsMajor()
    {
        string json = """
        {
            "id": "1.17.1",
            "java_version": {
                "component": "java-runtime-alpha",
                "major": 16
            }
        }
        """;

        int? major = ParseMajor(json);
        Assert.Equal(16, major);
    }

    [Fact]
    public void ParseJavaMajorFromVersionJson_InvalidOrMissing_ReturnsNull()
    {
        Assert.Null(ParseMajor("{}"));
        Assert.Null(ParseMajor("""{"javaVersion": {}}"""));
    }

    [Theory]
    [InlineData("""{"id":"1.12.2","downloads":{}}""")]
    [InlineData("""{"id":"1.6.4","libraries":[]}""")]
    public void ParseJavaMajorFromVersionJson_LegacyWithoutJavaVersion_ReturnsJava8(string json) =>
        Assert.Equal(8, ParseMajor(json));

    [Fact]
    public async Task ReloadCache_DiskCacheChanged_ReflectsNewValueWithoutNetwork()
    {
        string manifestJson = """
        {
            "versions": [
                { "id": "1.21.4", "type": "release", "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.4.json" }
            ]
        }
        """;
        Dictionary<Uri, string> responses = new()
        {
            [new Uri(MojangVersionCatalog.ManifestV2Url)] = manifestJson,
            [new Uri("https://piston-meta.mojang.com/v1/packages/test/1.21.4.json")] = """{"id":"1.21.4","javaVersion":{"majorVersion":21}}""",
        };
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        var writer = new MinecraftJavaRequirementService(mockHttp, _testTempDir);
        Assert.Equal(21, await writer.GetRequiredJavaMajorAsync("1.21.4", cancellationToken: TestContext.Current.CancellationToken));

        // 另一實例改寫磁碟快取後，原實例重新載入應取得新值且不再連網
        string cachePath = Path.Combine(_testTempDir, MojangVersionCatalog.VersionsCacheFileName);
        string cached = await File.ReadAllTextAsync(cachePath, TestContext.Current.CancellationToken);
        string updated = System.Text.RegularExpressions.Regex.Replace(cached, @"(?<=:\s*)21\b", "25");
        Assert.NotEqual(cached, updated);
        await File.WriteAllTextAsync(cachePath, updated, TestContext.Current.CancellationToken);
        int requestsBefore = mockHttp.RequestCount;

        writer.ReloadCache();

        Assert.Equal(25, await writer.GetRequiredJavaMajorAsync("1.21.4", cancellationToken: TestContext.Current.CancellationToken));
        Assert.Equal(requestsBefore, mockHttp.RequestCount);
    }

    private static int? ParseMajor(string json)
    {
        using var doc = JsonDocument.Parse(json);
        return MojangVersionCatalog.ParseJavaMajorFromVersionJson(doc.RootElement);
    }

    [Fact]
    public async Task GetRequiredJavaMajorAsync_CacheMiss_FetchesFromOfficialAndCaches()
    {
        string manifestJson = """
        {
            "versions": [
                {
                    "id": "1.21.4",
                    "type": "release",
                    "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.4.json"
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
            }
        }
        """;

        Dictionary<Uri, string> responses = [];
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        responses[new Uri(MojangVersionCatalog.ManifestV2Url)] = manifestJson;
        responses[new Uri("https://piston-meta.mojang.com/v1/packages/test/1.21.4.json")] = packageJson;

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        int major = await service.GetRequiredJavaMajorAsync("1.21.4", cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(21, major);

        // 驗證已寫入版本快取檔案
        string versionsCache = Path.Combine(_testTempDir, MojangVersionCatalog.VersionsCacheFileName);
        Assert.True(File.Exists(versionsCache));

        // 第二次呼叫時命中快取，請求數不再增加
        int reqCountBefore = mockHttp.RequestCount;
        int secondFetch = await service.GetRequiredJavaMajorAsync("1.21.4", cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(21, secondFetch);
        Assert.Equal(reqCountBefore, mockHttp.RequestCount);
    }

    [Fact]
    public async Task GetRequiredJavaMajorAsync_VersionNotFound_ThrowsInvalidOperationException()
    {
        string manifestJson = """
        {
            "versions": []
        }
        """;

        Dictionary<Uri, string> responses = [];
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        responses[new Uri(MojangVersionCatalog.ManifestV2Url)] = manifestJson;

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        // 嚴格禁止以版本號盲目推算，官方清單找不到即擲出例外
        await Assert.ThrowsAsync<InvalidOperationException>(() => service.GetRequiredJavaMajorAsync("9.99.99", cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task PreloadAllJavaRequirementsAsync_MultipleVersions_PreloadsAll()
    {
        string manifestJson = """
        {
            "versions": [
                {
                    "id": "1.21.4",
                    "type": "release",
                    "url": "https://piston-meta.mojang.com/v1/packages/test/1.21.4.json"
                },
                {
                    "id": "1.16.5",
                    "type": "release",
                    "url": "https://piston-meta.mojang.com/v1/packages/test/1.16.5.json"
                }
            ]
        }
        """;

        Dictionary<Uri, string> responses = [];
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        responses[new Uri(MojangVersionCatalog.ManifestV2Url)] = manifestJson;
        responses[new Uri("https://piston-meta.mojang.com/v1/packages/test/1.21.4.json")] = """{"javaVersion": {"majorVersion": 21}}""";
        responses[new Uri("https://piston-meta.mojang.com/v1/packages/test/1.16.5.json")] = """{"javaVersion": {"majorVersion": 8}}""";

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);
        var dict = await service.PreloadAllJavaRequirementsAsync(cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(2, dict.Count);
        Assert.Equal(21, dict["1.21.4"]);
        Assert.Equal(8, dict["1.16.5"]);

        string versionsCache = Path.Combine(_testTempDir, MojangVersionCatalog.VersionsCacheFileName);
        Assert.True(File.Exists(versionsCache));
    }

    [Fact]
    public async Task EnsureCacheLoaded_PaperCacheExists_ReadsEntries()
    {
        string paperCachePath = Path.Combine(_testTempDir, "paper_mc_versions_cache.json");
        string paperJson = """
        [
            {
                "Version": "1.21.4",
                "Stable": true,
                "JavaMajor": 21
            },
            {
                "Version": "1.20.4",
                "Stable": true,
                "JavaMajor": 17
            }
        ]
        """;
        await File.WriteAllTextAsync(paperCachePath, paperJson, TestContext.Current.CancellationToken);

        Dictionary<Uri, string> responses = [];
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        int major21 = await service.GetRequiredJavaMajorAsync("1.21.4", TestContext.Current.CancellationToken);
        int major17 = await service.GetRequiredJavaMajorAsync("1.20.4", TestContext.Current.CancellationToken);

        Assert.Equal(21, major21);
        Assert.Equal(17, major17);
        Assert.Equal(0, mockHttp.RequestCount); // 驗證零網路請求，完全命中本機快取
    }
}
