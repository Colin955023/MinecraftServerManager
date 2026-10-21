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
            ("MinecraftServerManager-framework-dependent.exe", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe"),
            ("MinecraftServerManager-framework-dependent.exe.sha256", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe.sha256"),
            ("MinecraftServerManager-self-contained.exe", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-self-contained.exe"),
            ("MinecraftServerManager-self-contained.exe.sha256", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-self-contained.exe.sha256"));

        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: false, isFrameworkDependent: false);
        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http, runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal("https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-self-contained.exe", result.DownloadUrl);
        Assert.Equal("https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-self-contained.exe.sha256", result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task SelectsFrameworkDependentWhenRunningFrameworkDependentAndRuntimeInstalled()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            ("MinecraftServerManager-framework-dependent.exe", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe"),
            ("MinecraftServerManager-framework-dependent.exe.sha256", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe.sha256"),
            ("MinecraftServerManager-self-contained.exe", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-self-contained.exe"),
            ("MinecraftServerManager-self-contained.exe.sha256", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-self-contained.exe.sha256"));

        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: true, isFrameworkDependent: true);
        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http, runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal("https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe", result.DownloadUrl);
        Assert.Equal("https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe.sha256", result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task RejectsFrameworkDependentWhenRuntimeNotInstalledAndOnlyFrameworkDependentAvailable()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            ("MinecraftServerManager-framework-dependent.exe", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe"),
            ("MinecraftServerManager-framework-dependent.exe.sha256", "https://github.com/Colin955023/MinecraftServerManager/releases/download/v99.0.0/MinecraftServerManager-framework-dependent.exe.sha256"));

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

    [Fact]
    public async Task IgnoresAssetsOutsideTrustedReleaseDownloadPath()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            ("MinecraftServerManager-self-contained.exe", "https://evil.example.com/sc.exe"),
            ("MinecraftServerManager-self-contained.exe.sha256", "https://github.com/Other/Repo/releases/download/99.0.0/sc.sha256"));

        var runtime = new FakeEnvironmentRuntimeInfo(hasRuntime: true, isFrameworkDependent: false);
        var checker = new UpdateCheckerService(new FakeHttpPort(json), runtime);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
        Assert.Null(result.Sha256ChecksumUrl);
    }
}
