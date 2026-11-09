using System.Diagnostics.CodeAnalysis;
using System.Text.Json.Nodes;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Services;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class UpdateCheckerServiceTests
{
    private static readonly string RepoUrl = AppInfo.RepositoryUrl;
    private const string SingleExeName = "MinecraftServerManager.exe";
    private const string SingleShaName = "MinecraftServerManager.exe.sha256";
    private const string LegacyScExeName = "MinecraftServerManager-self-contained.exe";
    private const string LegacyScShaName = "MinecraftServerManager-self-contained.exe.sha256";

    private sealed class FakeHttpPort(string? responseText) : IHttpPort
    {
        public Task<HttpJsonResponse<System.Text.Json.JsonDocument>> GetJsonDocumentAsync(Uri uri, CancellationToken cancellationToken = default) =>
            TestHttpJson.FromTextAsync(this, uri, cancellationToken);

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

    [RequiresUnreferencedCode("Calls System.Text.Json.Nodes.JsonArray.Add<T>(T)")]
    private static string BuildReleasePayload(string tagName, params (string Name, string Url)[] assets)
    {
        var root = new JsonObject
        {
            ["tag_name"] = tagName,
            ["name"] = $"Release {tagName}",
            ["body"] = "更新說明與修復內容",
            ["html_url"] = $"{RepoUrl}/releases/tag/{tagName}",
        };

        var assetArray = new JsonArray();
        foreach (var (name, url) in assets)
        {
            assetArray.Add(new JsonObject
            {
                ["name"] = name,
                ["browser_download_url"] = url,
            });
        }
        root["assets"] = assetArray;

        return root.ToJsonString();
    }

    [Fact]
    [RequiresUnreferencedCode("Testing reflection")]
    public async Task SelectsSingleExeAndPairsSha256()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            (SingleExeName, $"{RepoUrl}/releases/download/v99.0.0/{SingleExeName}"),
            (SingleShaName, $"{RepoUrl}/releases/download/v99.0.0/{SingleShaName}"));

        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal($"{RepoUrl}/releases/download/v99.0.0/{SingleExeName}", result.DownloadUrl);
        Assert.Equal($"{RepoUrl}/releases/download/v99.0.0/{SingleShaName}", result.Sha256ChecksumUrl);
    }

    [Fact]
    [RequiresUnreferencedCode("Testing reflection")]
    public async Task SelectsLegacySelfContainedWhenStandardExeNotPresent()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            (LegacyScExeName, $"{RepoUrl}/releases/download/v99.0.0/{LegacyScExeName}"),
            (LegacyScShaName, $"{RepoUrl}/releases/download/v99.0.0/{LegacyScShaName}"));

        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal($"{RepoUrl}/releases/download/v99.0.0/{LegacyScExeName}", result.DownloadUrl);
        Assert.Equal($"{RepoUrl}/releases/download/v99.0.0/{LegacyScShaName}", result.Sha256ChecksumUrl);
    }

    [Fact]
    [RequiresUnreferencedCode("Testing reflection")]
    public async Task LegacyV211CompatibilityContract_SingleExeAssetSelectedAndPaired()
    {
        // 2.1.1 舊版相容性契約驗證：
        // 驗證當 Release 僅包含單一 MinecraftServerManager.exe 與 .sha256 時，
        // 舊版與新版更新機制均能自動匹配選中，確保舊版用戶可無縫升級至 v2.2.0。
        string json = BuildReleasePayload(
            "2.2.0",
            (SingleExeName, $"{RepoUrl}/releases/download/v2.2.0/{SingleExeName}"),
            (SingleShaName, $"{RepoUrl}/releases/download/v2.2.0/{SingleShaName}"));

        var http = new FakeHttpPort(json);
        var checker = new UpdateCheckerService(http);

        var result = await checker.CheckForUpdateAsync();

        Assert.Equal($"{RepoUrl}/releases/download/v2.2.0/{SingleExeName}", result.DownloadUrl);
        Assert.Equal($"{RepoUrl}/releases/download/v2.2.0/{SingleShaName}", result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task HandlesEmptyResponseGracefully()
    {
        var http = new FakeHttpPort(null);
        var checker = new UpdateCheckerService(http);

        var result = await checker.CheckForUpdateAsync();

        Assert.False(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
    }

    [Fact]
    [RequiresUnreferencedCode("Testing reflection")]
    public async Task IgnoresAssetsOutsideTrustedReleaseDownloadPath()
    {
        string json = BuildReleasePayload(
            "99.0.0",
            (SingleExeName, "https://evil.example.com/sc.exe"),
            (SingleShaName, "https://github.com/Other/Repo/releases/download/99.0.0/sc.sha256"));

        var checker = new UpdateCheckerService(new FakeHttpPort(json));

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
        Assert.Null(result.Sha256ChecksumUrl);
    }
}
