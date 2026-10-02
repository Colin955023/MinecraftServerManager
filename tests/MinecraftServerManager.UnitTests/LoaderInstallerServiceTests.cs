using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Loaders;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class LoaderInstallerServiceTests : IDisposable
{
    private readonly string _testRoot;
    private readonly string _cacheDir;
    private readonly string _serverDir;

    public LoaderInstallerServiceTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-installer-tests-" + Guid.NewGuid().ToString("N"));
        _cacheDir = Path.Combine(_testRoot, "cache");
        _serverDir = Path.Combine(_testRoot, "server");
        Directory.CreateDirectory(_cacheDir);
        Directory.CreateDirectory(_serverDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testRoot))
            {
                Directory.Delete(_testRoot, recursive: true);
            }
        }
        catch
        {
        }
    }

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

        var http = new MockInstallerHttpPort(paperBuildJson: paperBuildJson);
        var runner = new MockInstallerProcessRunner(0);
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

    [Fact]
    public async Task InstallLoaderFabricBuildsCorrectArgsAndDetectsTarget()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        var http = new MockInstallerHttpPort("", "");
        var runner = new MockInstallerProcessRunner(0, onRun: () =>
        {
            // 模擬 installer 產出檔案
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

        var spec = runner.LastSpec;
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

        var http = new MockInstallerHttpPort(manifestJson, metaJson);
        var runner = new MockInstallerProcessRunner(0, onRun: () =>
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
        var http = new MockInstallerHttpPort("", "");
        var runner = new MockInstallerProcessRunner(0, onRun: () =>
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

        var spec = runner.LastSpec;
        Assert.NotNull(spec);
        Assert.Contains("--installServer", spec.Arguments);
    }

    [Fact]
    public async Task InstallLoaderThrowsWhenProcessExitCodeIsNotZero()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        var http = new MockInstallerHttpPort("", "");
        var runner = new MockInstallerProcessRunner(1);

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

    private sealed class MockInstallerHttpPort(
        string manifestJson = "",
        string metaJson = "",
        string paperBuildJson = "") : IHttpPort
    {
        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default)
        {
            if (uri.AbsoluteUri.Contains("papermc.io", StringComparison.OrdinalIgnoreCase))
            {
                return Task.FromResult<string?>(paperBuildJson);
            }
            if (uri.AbsoluteUri.Contains("version_manifest", StringComparison.OrdinalIgnoreCase))
            {
                return Task.FromResult<string?>(manifestJson);
            }
            return Task.FromResult<string?>(metaJson);
        }

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default)
        {
            File.WriteAllText(targetPath, "dummy downloaded content");
            return Task.FromResult(new HttpResult(true));
        }

        public Task<string?> PostJsonAsync(
            Uri uri,
            string jsonPayload,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<string?>(null);
    }

    private sealed class MockInstallerProcessRunner(int exitCode, Action? onRun = null) : IProcessRunner
    {
        public ProcessStartSpec? LastSpec { get; private set; }

        public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default)
        {
            LastSpec = specification;
            onRun?.Invoke();
            return Task.FromResult<IManagedProcess>(new MockInstallerProcess(exitCode));
        }
    }

    private sealed class MockInstallerProcess(int exitCode) : IManagedProcess
    {
        public int Pid => 999;
        public bool HasExited => true;
        public int? ExitCode => exitCode;

        public event Action<ProcessOutput>? OutputReceived
        {
            add { }
            remove { }
        }

        public Task WriteLineAsync(string line, CancellationToken cancellationToken = default) => Task.CompletedTask;

        public Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new ProcessExitResult(exitCode, false));

        public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default) =>
            Task.FromResult(new ProcessExitResult(exitCode, false));

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
