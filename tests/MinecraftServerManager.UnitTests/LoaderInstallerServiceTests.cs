using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Loaders;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed partial class LoaderInstallerServiceTests : IDisposable
{
    private readonly TempDirectory _testRootTemp = new("msm-installer-tests-");
    private readonly string _testRoot;
    private readonly string _cacheDir;
    private readonly string _serverDir;

    public LoaderInstallerServiceTests()
    {
        _testRoot = _testRootTemp.FullName;
        _cacheDir = Path.Combine(_testRoot, "cache");
        _serverDir = Path.Combine(_testRoot, "server");
        Directory.CreateDirectory(_cacheDir);
        Directory.CreateDirectory(_serverDir);
    }

    public void Dispose() => _testRootTemp.Dispose();

    [Fact]
    public async Task InstallLoaderPaperDownloadsServerJarSuccessfully()
    {
        string paperBuildJson = """
        {
            "downloads": {
                "server:application": {
                    "name": "paper-1.20.4-497.jar",
                    "url": "https://fill-data.papermc.io/v3/projects/paper/versions/1.20.4/builds/497/download",
                    "checksums": {
                        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                    }
                }
            }
        }
        """;

        var http = CreateHttpPort(paperBuildJson: paperBuildJson);
        var runner = new StubProcessRunner(0);
        var service = new LoaderInstallerService(http, runner, _cacheDir);

        string target = await service.InstallLoaderAsync(
            LoaderKind.Paper,
            minecraftVersion: "1.20.4",
            loaderVersion: "497",
            serverDirectory: _serverDir,
            javaExecutablePath: "java.exe");

        Assert.Equal("paper-1.20.4-497.jar", target);
        Assert.True(File.Exists(Path.Combine(_serverDir, "paper-1.20.4-497.jar")));
    }

    [Theory]
    [InlineData("../../evil.jar", "evil.jar")]
    [InlineData("payload.exe", "paper.jar")]
    public async Task InstallLoaderPaperSanitizesApiFileName(string apiName, string expectedJar)
    {
        string paperBuildJson = $$"""
        {
            "downloads": {
                "server:application": {
                    "name": "{{apiName}}",
                    "url": "https://fill-data.papermc.io/v3/projects/paper/versions/1.20.4/builds/497/download",
                    "checksums": { "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" }
                }
            }
        }
        """;

        var service = new LoaderInstallerService(CreateHttpPort(paperBuildJson: paperBuildJson), new StubProcessRunner(0), _cacheDir);

        string target = await service.InstallLoaderAsync(LoaderKind.Paper, "1.20.4", "497", _serverDir, "java.exe");

        Assert.Equal(expectedJar, target);
        Assert.True(File.Exists(Path.Combine(_serverDir, expectedJar)));
    }

    [Fact]
    public async Task InstallLoaderFabricBuildsCorrectArgsAndDetectsTarget()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        var http = CreateHttpPort("", "");
        var runner = new StubProcessRunner(0, onStart: _ =>
        {
            File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "dummy launch");
        });

        var service = new LoaderInstallerService(http, runner, _cacheDir);

        string target = await service.InstallLoaderAsync(
            LoaderKind.Fabric,
            minecraftVersion: "1.20.4",
            loaderVersion: "0.15.7",
            serverDirectory: _serverDir,
            javaExecutablePath: "java.exe");

        Assert.Equal("fabric-server-launch.jar", target);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.Contains("server", spec.Arguments);
        Assert.Contains("-mcversion", spec.Arguments);
        Assert.Contains("1.20.4", spec.Arguments);
        Assert.Contains("-loader", spec.Arguments);
        Assert.Contains("0.15.7", spec.Arguments);
    }

    [Fact]
    public async Task InstallLoaderFabricDownloadsVanillaServerJarWhenNotExists()
    {
        string manifestJson = """
        {
            "versions": [
                {
                    "id": "1.20.4",
                    "type": "release",
                    "url": "https://piston-meta.mojang.com/v1/packages/test/1.20.4.json"
                }
            ]
        }
        """;

        string metaJson = """
        {
            "downloads": {
                "server": {
                    "sha1": "testsha",
                    "size": 1234,
                    "url": "https://piston-data.mojang.com/v1/objects/test/server.jar"
                }
            }
        }
        """;

        var http = CreateHttpPort(manifestJson, metaJson);
        var runner = new StubProcessRunner(0, onStart: _ =>
        {
            File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "dummy launch");
        });

        var service = new LoaderInstallerService(http, runner, _cacheDir);

        string target = await service.InstallLoaderAsync(
            LoaderKind.Fabric,
            minecraftVersion: "1.20.4",
            loaderVersion: "0.15.7",
            serverDirectory: _serverDir,
            javaExecutablePath: "java.exe");

        Assert.Equal("fabric-server-launch.jar", target);
        Assert.True(File.Exists(Path.Combine(_serverDir, "server.jar")), "Fabric 安裝應預先下載原版 server.jar");
    }

    [Fact]
    public async Task InstallLoaderForgeDetectsRunBatWhenCreated()
    {
        var http = CreateHttpPort("", "");
        var runner = new StubProcessRunner(0, onStart: _ =>
        {
            File.WriteAllText(Path.Combine(_serverDir, "run.bat"), "@echo off\n");
        });

        var service = new LoaderInstallerService(http, runner, _cacheDir);

        string target = await service.InstallLoaderAsync(
            LoaderKind.Forge,
            minecraftVersion: "1.20.4",
            loaderVersion: "49.0.1",
            serverDirectory: _serverDir,
            javaExecutablePath: "java.exe");

        Assert.Equal("run.bat", target);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.Contains("--installServer", spec.Arguments);
    }

    [Fact]
    public async Task InstallLoaderThrowsWhenProcessExitCodeIsNotZero()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        var http = CreateHttpPort("", "");
        var runner = new StubProcessRunner(1);

        var service = new LoaderInstallerService(http, runner, _cacheDir);

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            service.InstallLoaderAsync(
                LoaderKind.Fabric,
                minecraftVersion: "1.20.4",
                loaderVersion: "0.15.7",
                serverDirectory: _serverDir,
                javaExecutablePath: "java.exe"));

        Assert.Contains("安裝失敗", ex.Message);
    }

    [Fact]
    public async Task InstallLoaderFabricFetchesMavenSha256AndPassesExpectedHash()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        string expectedHexSha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
        var http = CreateHttpPort(customGetText: uri => uri.AbsoluteUri.EndsWith(".sha256", StringComparison.OrdinalIgnoreCase)
            ? expectedHexSha256
            : null);
        var runner = new StubProcessRunner(0, onStart: _ =>
        {
            File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "dummy launch");
        });

        var service = new LoaderInstallerService(http, runner, _cacheDir);

        string target = await service.InstallLoaderAsync(
            LoaderKind.Fabric,
            minecraftVersion: "1.20.4",
            loaderVersion: "0.15.7",
            serverDirectory: _serverDir,
            javaExecutablePath: "java.exe");

        Assert.Equal("fabric-server-launch.jar", target);
        Assert.Equal(expectedHexSha256, http.LastDownloadExpectedHash);
        Assert.Equal("sha256", http.LastDownloadExpectedAlgorithm);
    }

    /// <summary>建立安裝器用 HTTP 替身：依網址回應 manifest／meta／Paper 建置 JSON，下載一律寫入固定內容</summary>
    private static StubHttpPort CreateHttpPort(
        string manifestJson = "",
        string metaJson = "",
        string paperBuildJson = "",
        Func<Uri, string?>? customGetText = null) =>
        new()
        {
            TextHandler = uri =>
            {
                if (customGetText?.Invoke(uri) is string custom)
                {
                    return custom;
                }

                if (uri.AbsoluteUri.Contains("papermc.io", StringComparison.OrdinalIgnoreCase))
                {
                    return paperBuildJson;
                }

                return uri.AbsoluteUri.Contains("version_manifest", StringComparison.OrdinalIgnoreCase) ? manifestJson : metaJson;
            },
            DownloadHandler = request =>
            {
                File.WriteAllText(request.TargetPath, "dummy downloaded content");
                return Task.FromResult(new HttpResult(true));
            },
        };
}
