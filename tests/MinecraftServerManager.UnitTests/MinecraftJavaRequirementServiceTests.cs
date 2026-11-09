using System.Diagnostics.CodeAnalysis;
using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Loaders;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed partial class MinecraftJavaRequirementServiceTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MinecraftJavaRequirementServiceTests));
    private readonly string _testTempDir;

    public MinecraftJavaRequirementServiceTests()
    {
        _testTempDir = Path.Combine(Path.GetTempPath(), "msm_java_req_test_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testTempDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testTempDir))
            {
                Directory.Delete(_testTempDir, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

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

        int major = await service.GetRequiredJavaMajorAsync("1.21.4");
        Assert.Equal(21, major);

        // 驗證已寫入版本快取檔案
        string versionsCache = Path.Combine(_testTempDir, MojangVersionCatalog.VersionsCacheFileName);
        Assert.True(File.Exists(versionsCache));

        // 第二次呼叫時命中快取，請求數不再增加
        int reqCountBefore = mockHttp.RequestCount;
        int secondFetch = await service.GetRequiredJavaMajorAsync("1.21.4");
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
        await Assert.ThrowsAsync<InvalidOperationException>(() => service.GetRequiredJavaMajorAsync("9.99.99"));
    }

    [Fact]
    public async Task PreloadAllJavaRequirementsAsync_PreloadsAllVersions()
    {
        string manifestJson = """
        {
            "versions": [
                {
                    "id": "1.21.4",
                    "type": "release",
                    "url": "https://example.com/1.21.4.json"
                },
                {
                    "id": "1.16.5",
                    "type": "release",
                    "url": "https://example.com/1.16.5.json"
                }
            ]
        }
        """;

        Dictionary<Uri, string> responses = [];
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        responses[new Uri(MojangVersionCatalog.ManifestV2Url)] = manifestJson;
        responses[new Uri("https://example.com/1.21.4.json")] = """{"javaVersion": {"majorVersion": 21}}""";
        responses[new Uri("https://example.com/1.16.5.json")] = """{"javaVersion": {"majorVersion": 8}}""";

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);
        var dict = await service.PreloadAllJavaRequirementsAsync();

        Assert.Equal(2, dict.Count);
        Assert.Equal(21, dict["1.21.4"]);
        Assert.Equal(8, dict["1.16.5"]);

        string versionsCache = Path.Combine(_testTempDir, MojangVersionCatalog.VersionsCacheFileName);
        Assert.True(File.Exists(versionsCache));
    }

    [Fact]
    public async Task EnsureCacheLoadedReadsPaperMcVersionsCacheSuccessfully()
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
        await File.WriteAllTextAsync(paperCachePath, paperJson);

        Dictionary<Uri, string> responses = [];
        var mockHttp = new StubHttpPort(uri => responses.GetValueOrDefault(uri));
        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        int major21 = await service.GetRequiredJavaMajorAsync("1.21.4", Domain.Servers.LoaderKind.Paper);
        int major17 = await service.GetRequiredJavaMajorAsync("1.20.4", Domain.Servers.LoaderKind.Paper);

        Assert.Equal(21, major21);
        Assert.Equal(17, major17);
        Assert.Equal(0, mockHttp.RequestCount); // 驗證零網路請求，完全命中本地快取
    }
}
