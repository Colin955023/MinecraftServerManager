using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Java;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class MinecraftJavaRequirementServiceTests : IDisposable
{
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
        catch
        {
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

        int? major = MinecraftJavaRequirementService.ParseJavaMajorFromVersionJson(json);
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

        int? major = MinecraftJavaRequirementService.ParseJavaMajorFromVersionJson(json);
        Assert.Equal(16, major);
    }

    [Fact]
    public void ParseJavaMajorFromVersionJson_InvalidOrMissing_ReturnsNull()
    {
        Assert.Null(MinecraftJavaRequirementService.ParseJavaMajorFromVersionJson(string.Empty));
        Assert.Null(MinecraftJavaRequirementService.ParseJavaMajorFromVersionJson("{}"));
        Assert.Null(MinecraftJavaRequirementService.ParseJavaMajorFromVersionJson("""{"javaVersion": {}}"""));
    }

    [Fact]
    public async Task GetRequiredJavaMajorAsync_WhenCacheFileExists_LoadsAndReturnsWithoutHttp()
    {
        string cacheFile = Path.Combine(_testTempDir, MinecraftJavaRequirementService.RequirementsCacheFileName);
        var initialCache = new Dictionary<string, int>
        {
            ["1.21.4"] = 21,
            ["1.20.1"] = 17,
            ["1.12.2"] = 8
        };
        await File.WriteAllTextAsync(cacheFile, JsonSerializer.Serialize(initialCache));

        var mockHttp = new MockHttpPort();
        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        int major = await service.GetRequiredJavaMajorAsync("1.21.4");
        Assert.Equal(21, major);
        Assert.Equal(0, mockHttp.RequestCount); // 完全不發出 HTTP 請求

        int? cached = service.GetCachedJavaMajor("1.20.1");
        Assert.Equal(17, cached);
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

        var mockHttp = new MockHttpPort();
        mockHttp.Responses[new Uri(MinecraftJavaRequirementService.ManifestV2Url)] = manifestJson;
        mockHttp.Responses[new Uri("https://piston-meta.mojang.com/v1/packages/test/1.21.4.json")] = packageJson;

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        int major = await service.GetRequiredJavaMajorAsync("1.21.4");
        Assert.Equal(21, major);

        // 驗證已寫入磁碟快取檔案
        string cacheFile = Path.Combine(_testTempDir, MinecraftJavaRequirementService.RequirementsCacheFileName);
        Assert.True(File.Exists(cacheFile));

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

        var mockHttp = new MockHttpPort();
        mockHttp.Responses[new Uri(MinecraftJavaRequirementService.ManifestV2Url)] = manifestJson;

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);

        // 嚴格禁止以版本號盲目推算，官方清單找不到即拋出例外
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

        var mockHttp = new MockHttpPort();
        mockHttp.Responses[new Uri(MinecraftJavaRequirementService.ManifestV2Url)] = manifestJson;
        mockHttp.Responses[new Uri("https://example.com/1.21.4.json")] = """{"javaVersion": {"majorVersion": 21}}""";
        mockHttp.Responses[new Uri("https://example.com/1.16.5.json")] = """{"javaVersion": {"majorVersion": 8}}""";

        var service = new MinecraftJavaRequirementService(mockHttp, _testTempDir);
        var dict = await service.PreloadAllJavaRequirementsAsync();

        Assert.Equal(2, dict.Count);
        Assert.Equal(21, dict["1.21.4"]);
        Assert.Equal(8, dict["1.16.5"]);

        string cacheFile = Path.Combine(_testTempDir, MinecraftJavaRequirementService.RequirementsCacheFileName);
        Assert.True(File.Exists(cacheFile));
    }

    private sealed class MockHttpPort : IHttpPort
    {
        public Dictionary<Uri, string> Responses { get; } = [];
        public int RequestCount { get; private set; }

        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default)
        {
            RequestCount++;
            if (Responses.TryGetValue(uri, out string? response))
            {
                return Task.FromResult<string?>(response);
            }
            return Task.FromResult<string?>(null);
        }

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
