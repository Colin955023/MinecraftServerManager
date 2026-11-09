using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組檔案操作與交易安裝測試
/// </summary>
public sealed partial class ModFileInstallerTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModFileInstallerTests));
    private readonly string _testDir;
    private readonly string _modsDir;

    public ModFileInstallerTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_test_installer_" + Guid.NewGuid().ToString("N"));
        _modsDir = Path.Combine(_testDir, "mods");
        Directory.CreateDirectory(_modsDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testDir))
            {
                Directory.Delete(_testDir, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    [Fact]
    public async Task SetModStateAsyncEnableAndDisableShouldRenameFiles()
    {
        var installer = new ModFileInstaller(CreateHttpPort());
        string activeJar = Path.Combine(_modsDir, "testmod.jar");
        File.WriteAllText(activeJar, "dummy content");

        // 停用
        var disableResult = await installer.SetModStateAsync(_modsDir, "testmod", enable: false);
        Assert.True(disableResult.Completed);
        Assert.False(File.Exists(activeJar));
        Assert.True(File.Exists(Path.Combine(_modsDir, "testmod.jar.disabled")));

        // 啟用
        var enableResult = await installer.SetModStateAsync(_modsDir, "testmod", enable: true);
        Assert.True(enableResult.Completed);
        Assert.True(File.Exists(activeJar));
        Assert.False(File.Exists(Path.Combine(_modsDir, "testmod.jar.disabled")));
    }

    [Fact]
    public async Task SetModStateAsyncWithConflictDifferentContentShouldCreateBackup()
    {
        var installer = new ModFileInstaller(CreateHttpPort());
        string activeJar = Path.Combine(_modsDir, "conflictmod.jar");
        string disabledJar = Path.Combine(_modsDir, "conflictmod.jar.disabled");
        File.WriteAllText(activeJar, "version 1");
        File.WriteAllText(disabledJar, "version 2");

        // 當兩者都存在且內容不同，啟用操作應備份來源
        var result = await installer.SetModStateAsync(_modsDir, "conflictmod", enable: true);
        Assert.True(result.Completed);
        Assert.True(File.Exists(activeJar));
        string[] backupFiles = Directory.GetFiles(_modsDir, "conflictmod.conflict*.bak");
        Assert.Single(backupFiles);
    }

    [Fact]
    public async Task DeleteModsAsyncShouldRemoveSpecifiedFiles()
    {
        var installer = new ModFileInstaller(CreateHttpPort());
        string mod1 = Path.Combine(_modsDir, "mod1.jar");
        string mod2 = Path.Combine(_modsDir, "mod2.jar.disabled");
        File.WriteAllText(mod1, "content1");
        File.WriteAllText(mod2, "content2");

        var result = await installer.DeleteModsAsync(_modsDir, ["mod1", "mod2", "mod3"]);
        Assert.True(result.Partial);
        Assert.Equal(2, result.AffectedCount);
        Assert.Contains("1 個未找到", result.Message);
        Assert.False(File.Exists(mod1));
        Assert.False(File.Exists(mod2));
    }

    [Fact]
    public async Task ImportLocalModAsyncShouldRejectNonJarFiles()
    {
        var installer = new ModFileInstaller(CreateHttpPort());
        string textFile = Path.Combine(_testDir, "test.txt");
        File.WriteAllText(textFile, "not a jar");

        var result = await installer.ImportLocalModAsync(_modsDir, textFile);
        Assert.True(result.Failed);
    }

    [Fact]
    public async Task ImportLocalModAsyncShouldCopyJarFile()
    {
        var installer = new ModFileInstaller(CreateHttpPort());
        string jarFile = Path.Combine(_testDir, "imported.jar");
        File.WriteAllText(jarFile, "jar content");

        var result = await installer.ImportLocalModAsync(_modsDir, jarFile);
        Assert.True(result.Completed);
        Assert.True(File.Exists(Path.Combine(_modsDir, "imported.jar")));
    }

    [Fact]
    public async Task InstallRemoteModAsyncWhenDownloadFailsShouldRollback()
    {
        var fakeHttp = CreateHttpPort(shouldFail: true);
        var installer = new ModFileInstaller(fakeHttp);

        var result = await installer.InstallRemoteModAsync(
            _modsDir,
            "https://example.invalid/fail.jar",
            "fail.jar");

        Assert.True(result.Failed);
        Assert.False(File.Exists(Path.Combine(_modsDir, "fail.jar")));
    }

    [Fact]
    public async Task InstallRemoteModAsyncConcurrentDownloadsUseIsolatedStagingDirectories()
    {
        var installer = new ModFileInstaller(CreateHttpPort(delayMilliseconds: 25));

        ModFileOperationResult[] results = await Task.WhenAll(
            installer.InstallRemoteModAsync(_modsDir, "https://example.invalid/first.jar", "first.jar"),
            installer.InstallRemoteModAsync(_modsDir, "https://example.invalid/second.jar", "second.jar"));

        Assert.All(results, static result => Assert.True(result.Completed));
        Assert.True(File.Exists(Path.Combine(_modsDir, "first.jar")));
        Assert.True(File.Exists(Path.Combine(_modsDir, "second.jar")));
        Assert.Empty(Directory.GetDirectories(Path.Combine(_modsDir, ".download_staging")));
    }

    [Theory]
    [InlineData("https://cdn.modrinth.com/data/ABC/versions/1.0.jar", true)]
    [InlineData("https://modrinth.com/mod/sodium", true)]
    [InlineData("http://cdn.modrinth.com/data/ABC/versions/1.0.jar", false)]
    [InlineData("https://malicious.site/fake.jar", false)]
    [InlineData("https://cdn.modrinth.com.attacker.com/mod.jar", false)]
    [InlineData("https://sub.cdn.modrinth.com/mod.jar", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    [InlineData("not a url", false)]
    public void IsOfficialModrinthSource_ValidatesUrlsCorrectly(string? url, bool expected)
    {
        bool actual = ModFileInstaller.IsOfficialModrinthSource(url);
        Assert.Equal(expected, actual);
    }

    /// <summary>建立模擬下載的 HTTP 替身：可設定失敗與延遲，成功時寫入固定內容</summary>
    private static StubHttpPort CreateHttpPort(bool shouldFail = false, int delayMilliseconds = 0) =>
        new()
        {
            DownloadHandler = async request =>
            {
                if (delayMilliseconds > 0)
                {
                    await Task.Delay(delayMilliseconds, request.CancellationToken);
                }

                if (shouldFail)
                {
                    return new HttpResult(false, "網路連線失敗");
                }

                File.WriteAllText(request.TargetPath, "downloaded content");
                return new HttpResult(true, null, 18);
            },
        };
}
