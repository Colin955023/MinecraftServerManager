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

        var http = new StubHttpPort(json);
        var checker = new UpdateCheckerService(http);

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal($"{RepoUrl}/releases/download/v99.0.0/{SingleExeName}", result.DownloadUrl);
        Assert.Equal($"{RepoUrl}/releases/download/v99.0.0/{SingleShaName}", result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task HandlesEmptyResponseGracefully()
    {
        var http = new StubHttpPort();
        var checker = new UpdateCheckerService(http);

        var result = await checker.CheckForUpdateAsync();

        Assert.False(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
    }

    [Theory]
    [InlineData("not json at all")]
    [InlineData("[]")]
    [InlineData("""{"tag_name": 123}""")]
    public async Task InvalidReleasePayload_ReturnsNoUpdateWithoutThrowing(string payload)
    {
        var checker = new UpdateCheckerService(new StubHttpPort(payload));

        var result = await checker.CheckForUpdateAsync();

        Assert.False(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
        Assert.Null(result.Sha256ChecksumUrl);
    }

    [Fact]
    public async Task MissingOptionalFields_FallBackToTagNameAndDefaultReleasePage()
    {
        string json = """{"tag_name": "v99.0.0", "unknown_field": {"nested": [1, 2]}}""";
        var checker = new UpdateCheckerService(new StubHttpPort(json));

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Equal("v99.0.0", result.LatestVersion);
        Assert.Equal("v99.0.0", result.ReleaseTitle);
        Assert.Equal(string.Empty, result.ReleaseNotes);
        Assert.Equal(RepoUrl + "/releases", result.ReleasePageUrl);
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

        var checker = new UpdateCheckerService(new StubHttpPort(json));

        var result = await checker.CheckForUpdateAsync();

        Assert.True(result.HasUpdate);
        Assert.Null(result.DownloadUrl);
        Assert.Null(result.Sha256ChecksumUrl);
    }
}
