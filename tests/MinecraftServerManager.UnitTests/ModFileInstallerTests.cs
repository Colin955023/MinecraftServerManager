using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>模組檔案操作與交易安裝測試</summary>
public sealed partial class ModFileInstallerTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm_test_installer_");
    private readonly string _testDir;
    private readonly string _modsDir;

    public ModFileInstallerTests()
    {
        _testDir = _testDirTemp.FullName;
        _modsDir = Path.Combine(_testDir, "mods");
        Directory.CreateDirectory(_modsDir);
    }

    public void Dispose() => _testDirTemp.Dispose();

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
    public async Task SetModStateAsyncReportsFailureWhenFileIsLocked()
    {
        var installer = new ModFileInstaller(CreateHttpPort());
        string activeJar = Path.Combine(_modsDir, "lockedmod.jar");
        File.WriteAllText(activeJar, "dummy content");

        LocalModMutationResult result;
        using (new FileStream(activeJar, FileMode.Open, FileAccess.Read, FileShare.None))
        {
            result = await installer.SetModStateAsync(_modsDir, "lockedmod", enable: false);
        }

        Assert.False(result.Completed);
        Assert.True(File.Exists(activeJar));
        Assert.False(File.Exists(Path.Combine(_modsDir, "lockedmod.jar.disabled")));
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
        Assert.True(result.Completed);
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

    private const string ValidContent = "downloaded content";
    private static readonly string ValidSha512 = Infrastructure.Utilities.HashCalculator.DigestBytes(
        System.Text.Encoding.UTF8.GetBytes(ValidContent),
        "sha512");

    [Fact]
    public async Task InstallRemoteModAsyncWhenDownloadFailsShouldRollback()
    {
        var fakeHttp = CreateHttpPort(shouldFail: true);
        var installer = new ModFileInstaller(fakeHttp);

        var result = await installer.InstallRemoteModAsync(
            _modsDir,
            "https://cdn.modrinth.com/data/ABC/versions/1.0/fail.jar",
            "fail.jar",
            ValidSha512,
            "sha512");

        Assert.True(result.Failed);
        Assert.False(File.Exists(Path.Combine(_modsDir, "fail.jar")));
    }

    [Theory]
    [InlineData("https://example.invalid/mod.jar", "abcdef")]
    [InlineData("https://cdn.modrinth.com/data/ABC/versions/1.0/mod.jar", "")]
    [InlineData("https://cdn.modrinth.com/data/ABC/versions/1.0/mod.jar", null)]
    public async Task InstallRemoteModAsyncRejectsUnofficialUrlOrMissingHash(string url, string? expectedHash)
    {
        var installer = new ModFileInstaller(CreateHttpPort());

        var result = await installer.InstallRemoteModAsync(_modsDir, url, "mod.jar", expectedHash, "sha512");

        Assert.True(result.Failed);
        Assert.False(File.Exists(Path.Combine(_modsDir, "mod.jar")));
    }

    [Fact]
    public async Task InstallRemoteModAsyncConcurrentDownloadsUseIsolatedStagingDirectories()
    {
        var barrier = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        int entered = 0;
        var httpPort = new StubHttpPort
        {
            DownloadHandler = async request =>
            {
                if (Interlocked.Increment(ref entered) >= 2)
                {
                    barrier.TrySetResult();
                }

                await barrier.Task.WaitAsync(request.CancellationToken);
                File.WriteAllText(request.TargetPath, ValidContent);
                return new HttpResult(true, null, ValidContent.Length);
            }
        };
        var installer = new ModFileInstaller(httpPort);

        ModFileOperationResult[] results = await Task.WhenAll(
            installer.InstallRemoteModAsync(_modsDir, "https://cdn.modrinth.com/data/A/versions/1/first.jar", "first.jar", ValidSha512, "sha512"),
            installer.InstallRemoteModAsync(_modsDir, "https://cdn.modrinth.com/data/B/versions/1/second.jar", "second.jar", ValidSha512, "sha512"));

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

    /// <summary>建立模擬下載的 HTTP 替身：成功時寫入固定內容</summary>
    private static StubHttpPort CreateHttpPort(bool shouldFail = false) =>
        new()
        {
            DownloadHandler = request =>
            {
                if (shouldFail)
                {
                    return Task.FromResult(new HttpResult(false, "網路連線失敗"));
                }

                File.WriteAllText(request.TargetPath, "downloaded content");
                return Task.FromResult(new HttpResult(true, null, 18));
            },
        };
}
