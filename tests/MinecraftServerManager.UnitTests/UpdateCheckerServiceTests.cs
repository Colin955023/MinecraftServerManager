using System.Text.Json.Nodes;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Services;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class UpdateCheckerServiceTests
{
    private sealed class FakeEnvironmentRuntimeInfo(bool hasRuntime, bool isFrameworkDependent) : IEnvironmentRuntimeInfo
    {
        public bool IsNet10DesktopRuntimeInstalled() => hasRuntime;
        public bool IsCurrentProcessFrameworkDependent() => isFrameworkDependent;
    }

    private sealed class FakeHttpPort(string? responseText) : IHttpPort
    {
        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default) =>
            Task.FromResult(responseText);

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<string?> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();
    }

    private static string BuildReleasePayload(string tagName, params (string Name, string Url)[] assets)
    {
        var root = new JsonObject
        {
            ["tag_name"] = tagName,
            ["name"] = $"Release {tagName}",
            ["body"] = "更新說明與修復內容",
            ["html_url"] = $"https://github.com/Colin955023/MinecraftServerManager/releases/tag/{tagName}"
        };

        var assetArray = new JsonArray();
        foreach (var (name, url) in assets)
        {
            assetArray.Add(new JsonObject
            {
                ["name"] = name,
                ["browser_download_url"] = url
            });
        }
        root["assets"] = assetArray;

        return root.ToJsonString();
    }

    [Fact]
    public async Task SelectsSelfContainedByDefaultAndPairsSha256()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            ("MinecraftServerManager-framework-dependent.exe", "https://example.com/fd.exe"),
            ("MinecraftServerManager-framework-dependent.exe.sha256", "https://example.com/fd.sha256"),
            ("MinecraftServerManager-self-contained.exe", "https://example.com/sc.exe"),
            ("MinecraftServerManager-self-contained.exe.sha256", "https://example.com/sc.sha256"));

        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: false, isFrameworkDependent: false);
        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http, runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal("https://example.com/sc.exe", result.DownloadUrl);
        Assert.Equal("https://example.com/sc.sha256", result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task SelectsFrameworkDependentWhenRunningFrameworkDependentAndRuntimeInstalled()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            ("MinecraftServerManager-framework-dependent.exe", "https://example.com/fd.exe"),
            ("MinecraftServerManager-framework-dependent.exe.sha256", "https://example.com/fd.sha256"),
            ("MinecraftServerManager-self-contained.exe", "https://example.com/sc.exe"),
            ("MinecraftServerManager-self-contained.exe.sha256", "https://example.com/sc.sha256"));

        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: true, isFrameworkDependent: true);
        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http, runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal("https://example.com/fd.exe", result.DownloadUrl);
        Assert.Equal("https://example.com/fd.sha256", result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task RejectsFrameworkDependentWhenRuntimeNotInstalledAndOnlyFrameworkDependentAvailable()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            ("MinecraftServerManager-framework-dependent.exe", "https://example.com/fd.exe"),
            ("MinecraftServerManager-framework-dependent.exe.sha256", "https://example.com/fd.sha256"));

        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: false, isFrameworkDependent: false);
        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http, runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
        Assert.Contains("重要提示", result.ReleaseNotes);
        Assert.Contains("framework-dependent", result.ReleaseNotes);
    }

    [Fact]
    public async Task HandlesEmptyResponseGracefully()
    {
        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: false, isFrameworkDependent: false);
        var http = new FakeHttpPort(null);
        var checker = new UpdateCheckerService(http, runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.False(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
    }
}
