using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>Modrinth REST API 用戶端測試</summary>
public sealed class ModrinthClientTests
{
    [Fact]
    public async Task SearchModsAsyncShouldParseResponseCorrectly()
    {
        string jsonResponse = """
        {
            "hits": [
                {
                    "project_id": "AANobbMI",
                    "slug": "fabric-api",
                    "title": "Fabric API",
                    "description": "Core API library for Fabric mods",
                    "categories": ["fabric", "quilt"],
                    "client_side": "optional",
                    "server_side": "optional",
                    "downloads": 25000000,
                    "icon_url": "https://cdn.modrinth.com/icon.png",
                    "latest_version": "v_test_123",
                    "versions": ["1.20.1", "1.20.2"]
                }
            ],
            "offset": 0,
            "limit": 10,
            "total_hits": 1
        }
        """;

        string versionsBatchResponse = """
        [
            {
                "id": "v_test_123",
                "version_number": "0.5.8"
            }
        ]
        """;

        string? requestedUrl = null;
        var fakeHttp = CreateHttpPort(uri =>
        {
            string s = uri.AbsoluteUri;
            if (s.Contains("/search"))
            {
                requestedUrl = s;
                return jsonResponse;
            }

            if (s.Contains("/versions?ids="))
            {
                return versionsBatchResponse;
            }

            return null;
        });
        var client = new ModrinthClient(fakeHttp);

        var results = await client.SearchModsAsync("fabric-api", loader: "fabric", minecraftVersion: "1.20.1");

        var mod = Assert.Single(results);
        Assert.Equal("AANobbMI", mod.ProjectId);
        Assert.Equal("fabric-api", mod.Slug);
        Assert.Equal("Fabric API", mod.Name);
        Assert.Equal(25000000, mod.Downloads);
        Assert.Equal("0.5.8", mod.LatestVersion);

        Assert.NotNull(requestedUrl);
        Assert.Contains("server_side", Uri.UnescapeDataString(requestedUrl));
    }

    [Fact]
    public async Task SearchModsAsyncFiltersOutUnsupportedServerSideMods()
    {
        string jsonResponse = """
        {
            "hits": [
                {
                    "project_id": "client_only_1",
                    "slug": "sodium",
                    "title": "Sodium",
                    "description": "Client-only rendering mod",
                    "categories": ["fabric"],
                    "client_side": "required",
                    "server_side": "unsupported",
                    "downloads": 5000000,
                    "icon_url": "",
                    "latest_version": "v1",
                    "versions": ["1.20.1"]
                }
            ],
            "offset": 0,
            "limit": 10,
            "total_hits": 1
        }
        """;

        var fakeHttp = CreateHttpPort(uri => uri.AbsoluteUri.Contains("/search") ? jsonResponse : null);
        var client = new ModrinthClient(fakeHttp);

        var results = await client.SearchModsAsync("sodium", loader: "fabric", minecraftVersion: "1.20.1");
        Assert.Empty(results);
    }

    [Fact]
    public async Task GetProjectVersionsAsyncSkipsMalformedEntriesAndKeepsTheRest()
    {
        string jsonResponse = """
        [
            { "version_number": "broken-without-id" },
            { "id": "bad-file", "version_number": "0.1", "files": [ { "filename": "no-url.jar" } ] },
            { "id": "good", "version_number": "1.0", "files": [ { "url": "https://cdn.modrinth.com/data/a.jar", "filename": "a.jar" } ] }
        ]
        """;

        var client = new ModrinthClient(CreateHttpPort(uri => uri.AbsoluteUri.Contains("/version") ? jsonResponse : null));

        var versions = await client.GetProjectVersionsAsync("sodium");

        Assert.Equal("good", Assert.Single(versions).VersionId);
    }

    [Fact]
    public async Task GetProjectVersionsAsyncShouldParseVersionsAndDependencies()
    {
        string jsonResponse = """
        [
            {
                "id": "v12345",
                "project_id": "AANobbMI",
                "name": "Sodium 0.5.8",
                "version_number": "0.5.8",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "version_type": "release",
                "date_published": "2024-01-01T00:00:00Z",
                "downloads": 10000,
                "changelog": "Bug fixes",
                "files": [
                    {
                        "url": "https://cdn.modrinth.com/data/sodium.jar",
                        "filename": "sodium-fabric-0.5.8.jar",
                        "primary": true,
                        "size": 1024000,
                        "hashes": {
                            "sha1": "abcdef1",
                            "sha512": "abcdef512"
                        }
                    }
                ],
                "dependencies": [
                    {
                        "project_id": "P7dR8mSH",
                        "dependency_type": "required"
                    }
                ]
            }
        ]
        """;

        var fakeHttp = CreateHttpPort(uri => uri.AbsoluteUri.Contains("/version") ? jsonResponse : null);
        var client = new ModrinthClient(fakeHttp);

        var versions = await client.GetProjectVersionsAsync("sodium");

        var ver = Assert.Single(versions);
        Assert.Equal("v12345", ver.VersionId);
        Assert.Equal("0.5.8", ver.VersionNumber);
        var file = Assert.Single(ver.Files);
        Assert.Equal("sodium-fabric-0.5.8.jar", file.Filename);
        Assert.Equal("https://cdn.modrinth.com/data/sodium.jar", file.Url);
        var dep = Assert.Single(ver.Dependencies);
        Assert.Equal("P7dR8mSH", dep.ProjectId);
        Assert.Equal(ModDependencyType.Required, dep.DependencyType);
    }

    [Fact]
    public async Task LookupVersionsByHashesAsyncShouldReturnMatchingVersion()
    {
        string jsonResponse = """
        {
            "testsha1": {
                "id": "v999",
                "project_id": "proj1",
                "name": "Version 1.0",
                "version_number": "1.0",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "files": [
                    {
                        "url": "https://example.com/mod.jar",
                        "filename": "mod.jar",
                        "primary": true,
                        "size": 500,
                        "hashes": { "sha1": "testsha1" }
                    }
                ],
                "dependencies": []
            }
        }
        """;

        var fakeHttp = CreateHttpPort(uri => uri.AbsoluteUri.Contains("/version_files") ? jsonResponse : null);
        var client = new ModrinthClient(fakeHttp);

        var result = await client.LookupVersionsByHashesAsync(["testsha1"], "sha1");

        var ver = Assert.Single(result).Value;
        Assert.Equal("v999", ver.Version.VersionId);
        Assert.Equal("proj1", ver.ProjectId);
        Assert.Equal("mod.jar", ver.Version.Files[0].Filename);
    }


    [Fact]
    public async Task MalformedJsonResponse_ShouldNotThrowAndReturnSafeFallbacks()
    {
        string malformedJson = "{ invalid json content: true,,, ";
        var fakeHttp = CreateHttpPort(_ => malformedJson);
        var client = new ModrinthClient(fakeHttp);

        // 1. 搜尋在遭遇畸形 JSON 時，安全記錄並回傳空清單，不擲出未攔截例外
        var searchResults = await client.SearchModsAsync("test");
        Assert.Empty(searchResults);

        // 2. 批次雜湊查詢在遭遇畸形 JSON 時，安全回傳空字典
        var batchHashResult = await client.LookupVersionsByHashesAsync(["hash1", "hash2"]);
        Assert.Empty(batchHashResult);
    }

    [Fact]
    public async Task GetProjectTitlesAsyncMapsIdAndSlugToTitleAndCachesResults()
    {
        var fakeHttp = CreateHttpPort(uri =>
            uri.AbsoluteUri.Contains("/projects?ids=", StringComparison.Ordinal)
                ? """[{"id":"7tEfOcA7","slug":"geckolib","title":"GeckoLib"}]"""
                : null);
        var client = new ModrinthClient(fakeHttp);

        var first = await client.GetProjectTitlesAsync(["7tEfOcA7", "unknown-project"]);
        var second = await client.GetProjectTitlesAsync(["geckolib"]);

        Assert.Equal("GeckoLib", first["7tEfOcA7"]);
        Assert.False(first.ContainsKey("unknown-project"));
        Assert.Equal("GeckoLib", second["geckolib"]);
        Assert.Equal(1, fakeHttp.RequestCount);
    }

    private static StubHttpPort CreateHttpPort(Func<Uri, string?> handler) =>
        new() { TextHandler = handler, PostHandler = (uri, _) => handler(uri) };
}
