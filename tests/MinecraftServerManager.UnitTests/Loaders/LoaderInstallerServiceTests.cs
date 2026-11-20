using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Loaders;

public sealed class LoaderInstallerServiceTests : IDisposable
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
    public async Task InstallLoaderThrowsTimeoutExceptionWhenInstallerNeverExits()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        var runner = new StubProcessRunner(interactive: true);
        var service = new LoaderInstallerService(CreateHttpPort("", ""), runner, _cacheDir)
        {
            InstallerTimeout = TimeSpan.FromMilliseconds(200),
        };

        await Assert.ThrowsAsync<TimeoutException>(() =>
            service.InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe"));

        Assert.NotNull(runner.LastCreatedProcess);
        await runner.LastCreatedProcess.Disposed.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);
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

    [Fact]
    public async Task InstallLoaderFallsBackToSha1WhenSha256Missing()
    {
        string expectedSha1 = "0123456789abcdef0123456789abcdef01234567";
        var http = CreateHttpPort(
            customGetText: uri => uri.AbsoluteUri.EndsWith(".sha1", StringComparison.OrdinalIgnoreCase) ? expectedSha1 : null,
            installerSha256: null);
        var runner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "run.bat"), "@echo off\n"));

        await new LoaderInstallerService(http, runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Forge, "1.20.4", "49.0.1", _serverDir, "java.exe");

        Assert.Equal(expectedSha1, http.LastDownloadExpectedHash);
        Assert.Equal("sha1", http.LastDownloadExpectedAlgorithm);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task InstallLoaderRejectsInstallerWithoutRemoteHash(bool hashRequestThrows)
    {
        var http = CreateHttpPort(
            customGetText: uri => hashRequestThrows && uri.AbsoluteUri.Contains(".sha", StringComparison.OrdinalIgnoreCase)
                ? throw new HttpRequestException("連線失敗")
                : null,
            installerSha256: null);
        var runner = new StubProcessRunner(0);

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new LoaderInstallerService(http, runner, _cacheDir)
                .InstallLoaderAsync(LoaderKind.Forge, "1.20.4", "49.0.1", _serverDir, "java.exe"));

        Assert.Contains("雜湊", ex.Message);
        Assert.Equal(0, http.DownloadCount);
        Assert.Null(runner.LastSpecification);
        Assert.Empty(Directory.EnumerateFiles(_cacheDir));
    }

    [Fact]
    public async Task InstallLoaderFabricPrefersFirstStableEntryAndFallsBackToFirstWhenNoStable()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        string unstableFirstJson = """
        [
            { "url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.2.0-rc1/fabric-installer-1.2.0-rc1.jar", "version": "1.2.0-rc1", "stable": false },
            { "url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar", "version": "1.1.2", "stable": true }
        ]
        """;
        var runner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "ok"));
        await new LoaderInstallerService(CreateHttpPort(fabricMetaJson: unstableFirstJson), runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");
        Assert.Contains(Path.Combine(_cacheDir, "fabric-installer-1.1.2.jar"), runner.LastSpecification!.Arguments);

        string allUnstableJson = """
        [
            { "url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.2.0/fabric-installer-1.2.0.jar", "version": "1.2.0", "stable": false },
            { "url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar", "version": "1.1.2", "stable": false }
        ]
        """;
        await new LoaderInstallerService(CreateHttpPort(fabricMetaJson: allUnstableJson), runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");
        Assert.Contains(Path.Combine(_cacheDir, "fabric-installer-1.2.0.jar"), runner.LastSpecification!.Arguments);
    }

    [Fact]
    public async Task InstallLoaderQuiltUsesMetaSha256FirstAndFallsBackToMavenHash()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        var httpWithMetaHash = CreateHttpPort();
        var runner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "quilt-server-launch.jar"), "ok"));

        await new LoaderInstallerService(httpWithMetaHash, runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Quilt, "1.20.4", "0.26.0", _serverDir, "java.exe");

        Assert.Equal(1, httpWithMetaHash.RequestCount);
        Assert.Equal(DefaultInstallerSha256, httpWithMetaHash.LastDownloadExpectedHash);
        Assert.Equal("sha256", httpWithMetaHash.LastDownloadExpectedAlgorithm);
        Assert.Contains(Path.Combine(_cacheDir, "quilt-installer-0.15.1.jar"), runner.LastSpecification!.Arguments);

        // 移除已快取檔改測無 Meta hashes 時退回 Maven .sha256
        File.Delete(Path.Combine(_cacheDir, "quilt-installer-0.15.1.jar"));
        string noHashesQuiltJson = """
        [
            { "version": "0.15.2", "url": "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/0.15.2/quilt-installer-0.15.2.jar" }
        ]
        """;
        string mavenHash = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        var httpMavenFallback = CreateHttpPort(
            quiltMetaJson: noHashesQuiltJson,
            customGetText: uri => uri.AbsoluteUri.EndsWith(".sha256", StringComparison.OrdinalIgnoreCase) ? mavenHash : null);

        await new LoaderInstallerService(httpMavenFallback, runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Quilt, "1.20.4", "0.26.0", _serverDir, "java.exe");

        Assert.Equal(mavenHash, httpMavenFallback.LastDownloadExpectedHash);
        Assert.True(httpMavenFallback.RequestCount >= 2);
    }

    [Theory]
    [InlineData("http://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar")]
    [InlineData("https://evil.example.com/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar")]
    [InlineData("https://maven.fabricmc.net:8443/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar")]
    [InlineData("https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/other-tool.jar")]
    [InlineData("https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar?v=1")]
    public async Task InstallLoaderRejectsUntrustedDynamicInstallerUri(string invalidUrl)
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        string badMeta = $$"""[{ "url": "{{invalidUrl}}", "version": "1.1.2", "stable": true }]""";
        var http = CreateHttpPort(fabricMetaJson: badMeta);
        var runner = new StubProcessRunner(0);

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new LoaderInstallerService(http, runner, _cacheDir)
                .InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe"));

        Assert.Equal(0, http.DownloadCount);
        Assert.Null(runner.LastSpecification);
    }

    [Fact]
    public async Task InstallLoaderRefreshesMetadataAfterOneHourTtlExpires()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        int metaRequests = 0;
        var http = CreateHttpPort(customGetText: uri =>
        {
            if (uri.Host.Equals("meta.fabricmc.net", StringComparison.OrdinalIgnoreCase))
            {
                metaRequests++;
                return DefaultFabricInstallerMetaJson;
            }
            return null;
        });
        var clock = new MutableTimeProvider(new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero));
        var runner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "ok"));
        var service = new LoaderInstallerService(http, runner, _cacheDir) { TimeProvider = clock };

        await service.InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");
        clock.Advance(TimeSpan.FromMinutes(30));
        await service.InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");
        Assert.Equal(1, metaRequests);

        clock.Advance(TimeSpan.FromMinutes(31));
        await service.InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");
        Assert.Equal(2, metaRequests);
    }

    [Fact]
    public async Task InstallLoaderFallsBackToLatestIntactCachedInstallerWhenMetaFails()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        SeedCachedInstaller("fabric-installer-1.0.1.jar", "old-1.0.1");
        SeedCachedInstaller("fabric-installer-1.1.2.jar", "new-1.1.2");
        SeedCachedInstaller("fabric-installer-1.2.0.jar", "corrupt-1.2.0", overrideHash: new string('f', 64));

        var http = CreateHttpPort(customGetText: uri =>
            uri.Host.Equals("meta.fabricmc.net", StringComparison.OrdinalIgnoreCase)
                ? throw new HttpRequestException("offline")
                : null);
        var runner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "ok"));

        await new LoaderInstallerService(http, runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");

        Assert.Equal(0, http.DownloadCount);
        Assert.Contains(Path.Combine(_cacheDir, "fabric-installer-1.1.2.jar"), runner.LastSpecification!.Arguments);
    }

    [Fact]
    public async Task InstallLoaderCleansOldFabricInstallersAndKeepsRecentFiveForForge()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        SeedCachedInstaller("fabric-installer-1.0.1.jar", "old");
        await File.WriteAllTextAsync(Path.Combine(_cacheDir, "fabric-installer-1.0.1.jar.part"), "part");
        await File.WriteAllTextAsync(Path.Combine(_cacheDir, "fabric-installer-1.1.2.jar.part"), "stale-part");
        SeedCachedInstaller("quilt-installer-0.15.1.jar", "keep-other-loader");

        var runner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "fabric-server-launch.jar"), "ok"));
        await new LoaderInstallerService(CreateHttpPort(), runner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe");

        Assert.True(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.1.2.jar")));
        Assert.True(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.1.2.jar.sha256")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.0.1.jar")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.0.1.jar.sha256")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.0.1.jar.part")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.1.2.jar.part")));
        Assert.True(File.Exists(Path.Combine(_cacheDir, "quilt-installer-0.15.1.jar")));

        // Forge 預置 6 份歷史版與 1 份孤兒 .sha256，執行後應保留最新 5 份（含本次）
        DateTime baseUtc = new(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        for (int i = 1; i <= 6; i++)
        {
            SeedCachedInstaller($"forge-1.20.1-47.0.{i}-installer.jar", $"forge-{i}", baseUtc.AddHours(i));
        }
        await File.WriteAllTextAsync(Path.Combine(_cacheDir, "forge-1.19.4-45.0.1-installer.jar.sha256"), "orphan");

        var forgeRunner = new StubProcessRunner(0, onStart: _ => File.WriteAllText(Path.Combine(_serverDir, "run.bat"), "@echo off\n"));
        await new LoaderInstallerService(CreateHttpPort(), forgeRunner, _cacheDir)
            .InstallLoaderAsync(LoaderKind.Forge, "1.20.4", "49.0.1", _serverDir, "java.exe");

        Assert.True(File.Exists(Path.Combine(_cacheDir, "forge-1.20.4-49.0.1-installer.jar")));
        Assert.True(File.Exists(Path.Combine(_cacheDir, "forge-1.20.1-47.0.6-installer.jar")));
        Assert.True(File.Exists(Path.Combine(_cacheDir, "forge-1.20.1-47.0.3-installer.jar")));
        Assert.True(File.Exists(Path.Combine(_cacheDir, "forge-1.20.1-47.0.3-installer.jar.sha256")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "forge-1.20.1-47.0.2-installer.jar")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "forge-1.20.1-47.0.2-installer.jar.sha256")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "forge-1.20.1-47.0.1-installer.jar")));
        Assert.False(File.Exists(Path.Combine(_cacheDir, "forge-1.19.4-45.0.1-installer.jar.sha256")));
    }

    [Fact]
    public async Task InstallLoaderKeepsExistingCacheWhenRemoteHashMissingAndDownloadRefused()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy vanilla");
        SeedCachedInstaller("fabric-installer-1.0.1.jar", "intact-old");
        var http = CreateHttpPort(installerSha256: null);

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new LoaderInstallerService(http, new StubProcessRunner(0), _cacheDir)
                .InstallLoaderAsync(LoaderKind.Fabric, "1.20.4", "0.15.7", _serverDir, "java.exe"));

        Assert.True(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.0.1.jar")));
        Assert.True(File.Exists(Path.Combine(_cacheDir, "fabric-installer-1.0.1.jar.sha256")));
    }

    private void SeedCachedInstaller(string fileName, string content, DateTime? lastWriteUtc = null, string? overrideHash = null)
    {
        string jarPath = Path.Combine(_cacheDir, fileName);
        byte[] bytes = System.Text.Encoding.UTF8.GetBytes(content);
        File.WriteAllBytes(jarPath, bytes);
        if (lastWriteUtc is DateTime ts)
        {
            File.SetLastWriteTimeUtc(jarPath, ts);
        }

        string hash = overrideHash ?? HashCalculator.DigestBytes(bytes);
        File.WriteAllText(jarPath + ".sha256", hash);
    }

    private sealed class MutableTimeProvider(DateTimeOffset initialUtc) : TimeProvider
    {
        private DateTimeOffset _utcNow = initialUtc;
        public override DateTimeOffset GetUtcNow() => _utcNow;
        public void Advance(TimeSpan delta) => _utcNow = _utcNow.Add(delta);
    }

    private const string DefaultInstallerSha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    private const string DefaultFabricInstallerMetaJson = """
        [
            {
                "url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar",
                "maven": "net.fabricmc:fabric-installer:1.1.2",
                "version": "1.1.2",
                "stable": true
            }
        ]
        """;

    private const string DefaultQuiltInstallerMetaJson = """
        [
            {
                "maven": "org.quiltmc:quilt-installer:0.15.1",
                "version": "0.15.1",
                "url": "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/0.15.1/quilt-installer-0.15.1.jar",
                "hashes": {
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                }
            }
        ]
        """;

    /// <summary>建立安裝器用 HTTP 替身；<paramref name="installerSha256"/> 為 null 代表遠端無 .sha256</summary>
    private static StubHttpPort CreateHttpPort(
        string manifestJson = "",
        string metaJson = "",
        string paperBuildJson = "",
        Func<Uri, string?>? customGetText = null,
        string? installerSha256 = DefaultInstallerSha256,
        string? fabricMetaJson = DefaultFabricInstallerMetaJson,
        string? quiltMetaJson = DefaultQuiltInstallerMetaJson) =>
        new()
        {
            TextHandler = uri =>
            {
                if (customGetText?.Invoke(uri) is string custom)
                {
                    return custom;
                }

                if (uri.Host.Equals("meta.fabricmc.net", StringComparison.OrdinalIgnoreCase) &&
                    uri.AbsolutePath.Equals("/v2/versions/installer", StringComparison.OrdinalIgnoreCase))
                {
                    return fabricMetaJson;
                }

                if (uri.Host.Equals("meta.quiltmc.org", StringComparison.OrdinalIgnoreCase) &&
                    uri.AbsolutePath.Equals("/v3/versions/installer", StringComparison.OrdinalIgnoreCase))
                {
                    return quiltMetaJson;
                }

                if (uri.AbsoluteUri.EndsWith(".sha256", StringComparison.OrdinalIgnoreCase))
                {
                    return installerSha256;
                }

                if (uri.AbsoluteUri.EndsWith(".sha1", StringComparison.OrdinalIgnoreCase))
                {
                    return null;
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
