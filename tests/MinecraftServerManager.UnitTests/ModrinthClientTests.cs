using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// Modrinth REST API 客戶端測試
/// </summary>
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
        var fakeHttp = new FakeHttpPort(uri =>
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

        Assert.Single(results);
        var mod = results[0];
        Assert.Equal("AANobbMI", mod.Id);
        Assert.Equal("fabric-api", mod.Slug);
        Assert.Equal("Fabric API", mod.Title);
        Assert.Equal(25000000, mod.Downloads);
        Assert.Equal("0.5.8", mod.LatestVersion);
        Assert.Equal("https://cdn.modrinth.com/icon.png", mod.IconUrl);
        Assert.Contains("fabric", mod.Loaders);

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

        var fakeHttp = new FakeHttpPort(uri => uri.AbsoluteUri.Contains("/search") ? jsonResponse : null);
        var client = new ModrinthClient(fakeHttp);

        var results = await client.SearchModsAsync("sodium", loader: "fabric", minecraftVersion: "1.20.1");
        Assert.Empty(results);
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

        var fakeHttp = new FakeHttpPort(uri => uri.AbsoluteUri.Contains("/version") ? jsonResponse : null);
        var client = new ModrinthClient(fakeHttp);

        var versions = await client.GetProjectVersionsAsync("sodium");

        Assert.Single(versions);
        var ver = versions[0];
        Assert.Equal("v12345", ver.Id);
        Assert.Equal("0.5.8", ver.VersionNumber);
        Assert.Single(ver.Files);
        Assert.Equal("sodium-fabric-0.5.8.jar", ver.Files[0].Filename);
        Assert.Equal("https://cdn.modrinth.com/data/sodium.jar", ver.Files[0].Url);
        Assert.Single(ver.Dependencies);
        Assert.Equal("P7dR8mSH", ver.Dependencies[0].ProjectId);
        Assert.Equal(ModDependencyType.Required, ver.Dependencies[0].DependencyType);
    }

    [Fact]
    public async Task GetVersionByHashAsyncShouldReturnMatchingVersion()
    {
        string jsonResponse = """
        {
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
        """;

        var fakeHttp = new FakeHttpPort(uri => uri.AbsoluteUri.Contains("/version_file/") ? jsonResponse : null);
        var client = new ModrinthClient(fakeHttp);

        var ver = await client.GetVersionByHashAsync("testsha1", "sha1");

        Assert.NotNull(ver);
        Assert.Equal("v999", ver.Version.Id);
        Assert.Equal("mod.jar", ver.Version.Files[0].Filename);
    }

    private sealed class FakeHttpPort(Func<Uri, string?> handler) : IHttpPort
    {
        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default) =>
            Task.FromResult(handler(uri));

        public Task<string?> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) =>
            Task.FromResult(handler(uri));
    }
}
