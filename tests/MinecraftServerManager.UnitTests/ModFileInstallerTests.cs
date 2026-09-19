using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組檔案操作與交易安裝測試
/// </summary>
public sealed class ModFileInstallerTests : IDisposable
{
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
        catch
        {
        }
    }

    [Fact]
    public async Task SetModStateAsyncEnableAndDisableShouldRenameFiles()
    {
        var installer = new ModFileInstaller(new FakeHttpPort());
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
        var installer = new ModFileInstaller(new FakeHttpPort());
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
        var installer = new ModFileInstaller(new FakeHttpPort());
        string mod1 = Path.Combine(_modsDir, "mod1.jar");
        string mod2 = Path.Combine(_modsDir, "mod2.jar.disabled");
        File.WriteAllText(mod1, "content1");
        File.WriteAllText(mod2, "content2");

        var result = await installer.DeleteModsAsync(_modsDir, ["mod1", "mod2", "mod3"]);
        Assert.True(result.Partial);
        Assert.Equal(2, result.AffectedCount);
        Assert.Contains("mod3", result.MissingIds);
        Assert.False(File.Exists(mod1));
        Assert.False(File.Exists(mod2));
    }

    [Fact]
    public async Task ImportLocalModAsyncShouldRejectNonJarFiles()
    {
        var installer = new ModFileInstaller(new FakeHttpPort());
        string textFile = Path.Combine(_testDir, "test.txt");
        File.WriteAllText(textFile, "not a jar");

        var result = await installer.ImportLocalModAsync(_modsDir, textFile);
        Assert.True(result.Failed);
    }

    [Fact]
    public async Task ImportLocalModAsyncShouldCopyJarFile()
    {
        var installer = new ModFileInstaller(new FakeHttpPort());
        string jarFile = Path.Combine(_testDir, "imported.jar");
        File.WriteAllText(jarFile, "jar content");

        var result = await installer.ImportLocalModAsync(_modsDir, jarFile);
        Assert.True(result.Completed);
        Assert.True(File.Exists(Path.Combine(_modsDir, "imported.jar")));
    }

    [Fact]
    public async Task InstallRemoteModAsyncWhenDownloadFailsShouldRollback()
    {
        var fakeHttp = new FakeHttpPort { ShouldFailDownload = true };
        var installer = new ModFileInstaller(fakeHttp);

        var result = await installer.InstallRemoteModAsync(
            _modsDir,
            "https://example.invalid/fail.jar",
            "fail.jar");

        Assert.True(result.Failed);
        Assert.False(File.Exists(Path.Combine(_modsDir, "fail.jar")));
    }

    private sealed class FakeHttpPort : IHttpPort
    {
        public bool ShouldFailDownload { get; set; }

        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default)
        {
            if (ShouldFailDownload)
            {
                return Task.FromResult(new HttpResult(false, "網路連線失敗"));
            }

            File.WriteAllText(targetPath, "downloaded content");
            return Task.FromResult(new HttpResult(true, null, 18));
        }

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<string?> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) =>
            Task.FromResult<string?>(null);
    }
}
