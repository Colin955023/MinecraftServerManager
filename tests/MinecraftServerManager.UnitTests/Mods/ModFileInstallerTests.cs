using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class ModFileInstallerTests : IDisposable
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
    public async Task SetModStateAsync_EnableAndDisable_RenamesFiles()
    {
        string activeJar = Path.Combine(_modsDir, "testmod.jar");
        File.WriteAllText(activeJar, "dummy content");

        // 停用
        var disableResult = await ModFileInstaller.SetModStateAsync(_modsDir, "testmod", enable: false, cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(disableResult.Completed);
        Assert.False(File.Exists(activeJar));
        Assert.True(File.Exists(Path.Combine(_modsDir, "testmod.jar.disabled")));

        // 啟用
        var enableResult = await ModFileInstaller.SetModStateAsync(_modsDir, "testmod", enable: true, cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(enableResult.Completed);
        Assert.True(File.Exists(activeJar));
        Assert.False(File.Exists(Path.Combine(_modsDir, "testmod.jar.disabled")));
    }

    [Fact]
    public async Task SetModStateAsync_ConflictWithDifferentContent_CreatesBackup()
    {
        string activeJar = Path.Combine(_modsDir, "conflictmod.jar");
        string disabledJar = Path.Combine(_modsDir, "conflictmod.jar.disabled");
        File.WriteAllText(activeJar, "version 1");
        File.WriteAllText(disabledJar, "version 2");

        // 當兩者都存在且內容不同，啟用操作應備份來源
        var result = await ModFileInstaller.SetModStateAsync(_modsDir, "conflictmod", enable: true, cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(result.Completed);
        Assert.True(File.Exists(activeJar));
        string[] backupFiles = Directory.GetFiles(_modsDir, "conflictmod.conflict*.bak");
        Assert.Single(backupFiles);
    }

    [Fact]
    public async Task SetModStateAsync_SameLengthDifferentLastChunk_CreatesBackup()
    {
        byte[] content = new byte[200_000];
        File.WriteAllBytes(Path.Combine(_modsDir, "tailmod.jar"), content);
        content[^1] = 1;
        File.WriteAllBytes(Path.Combine(_modsDir, "tailmod.jar.disabled"), content);

        var result = await ModFileInstaller.SetModStateAsync(_modsDir, "tailmod", enable: true, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Completed);
        Assert.Single(Directory.GetFiles(_modsDir, "tailmod.conflict*.bak"));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(81920)]
    [InlineData(200_000)]
    public async Task SetModStateAsync_IdenticalContent_RemovesDuplicate(int length)
    {
        byte[] content = new byte[length];
        string disabledJar = Path.Combine(_modsDir, "samemod.jar.disabled");
        File.WriteAllBytes(Path.Combine(_modsDir, "samemod.jar"), content);
        File.WriteAllBytes(disabledJar, content);

        var result = await ModFileInstaller.SetModStateAsync(_modsDir, "samemod", enable: true, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Completed);
        Assert.False(File.Exists(disabledJar));
        Assert.Empty(Directory.GetFiles(_modsDir, "samemod.conflict*.bak"));
    }

    [Fact]
    public async Task SetModStateAsync_FileLocked_ReportsFailure()
    {
        string activeJar = Path.Combine(_modsDir, "lockedmod.jar");
        File.WriteAllText(activeJar, "dummy content");

        LocalModMutationResult result;
        using (new FileStream(activeJar, FileMode.Open, FileAccess.Read, FileShare.None))
        {
            result = await ModFileInstaller.SetModStateAsync(_modsDir, "lockedmod", enable: false, cancellationToken: TestContext.Current.CancellationToken);
        }

        Assert.False(result.Completed);
        Assert.True(File.Exists(activeJar));
        Assert.False(File.Exists(Path.Combine(_modsDir, "lockedmod.jar.disabled")));
    }

    [Fact]
    public async Task DeleteModsAsync_SpecifiedIds_RemovesFiles()
    {
        string mod1 = Path.Combine(_modsDir, "mod1.jar");
        string mod2 = Path.Combine(_modsDir, "mod2.jar.disabled");
        File.WriteAllText(mod1, "content1");
        File.WriteAllText(mod2, "content2");

        var result = await ModFileInstaller.DeleteModsAsync(_modsDir, ["mod1", "mod2", "mod3"], TestContext.Current.CancellationToken);
        Assert.True(result.Completed);
        Assert.Equal(2, result.AffectedCount);
        Assert.Contains("1 個未找到", result.Message);
        Assert.False(File.Exists(mod1));
        Assert.False(File.Exists(mod2));
    }

    [Fact]
    public async Task DeleteModsAsync_AmbiguousPrefix_SkipsMatches()
    {
        string extra = Path.Combine(_modsDir, "sodium-extra-1.0.jar");
        string fabric = Path.Combine(_modsDir, "sodium-fabric-1.0.jar");
        File.WriteAllText(extra, "a");
        File.WriteAllText(fabric, "b");

        var result = await ModFileInstaller.DeleteModsAsync(_modsDir, ["sodium"], TestContext.Current.CancellationToken);

        Assert.Equal(0, result.AffectedCount);
        Assert.True(File.Exists(extra));
        Assert.True(File.Exists(fabric));
    }

    [Fact]
    public async Task DeleteModsAsync_ExactNameAndPrefix_PrefersExact()
    {
        string exact = Path.Combine(_modsDir, "sodium.jar");
        string extra = Path.Combine(_modsDir, "sodium-extra-1.0.jar");
        File.WriteAllText(exact, "a");
        File.WriteAllText(extra, "b");

        var result = await ModFileInstaller.DeleteModsAsync(_modsDir, ["sodium"], TestContext.Current.CancellationToken);

        Assert.Equal(1, result.AffectedCount);
        Assert.False(File.Exists(exact));
        Assert.True(File.Exists(extra));
    }

    [Fact]
    public async Task DeleteModsAsync_EnabledAndDisabledVariants_RemovesBoth()
    {
        string enabled = Path.Combine(_modsDir, "dup.jar");
        string disabled = Path.Combine(_modsDir, "dup.jar.disabled");
        File.WriteAllText(enabled, "a");
        File.WriteAllText(disabled, "b");

        var result = await ModFileInstaller.DeleteModsAsync(_modsDir, ["dup"], TestContext.Current.CancellationToken);

        Assert.Equal(1, result.AffectedCount);
        Assert.False(File.Exists(enabled));
        Assert.False(File.Exists(disabled));
    }

    [Fact]
    public async Task ImportLocalModAsync_SourceInModsDirectory_KeepsFile()
    {
        string jar = Path.Combine(_modsDir, "inplace.jar");
        File.WriteAllText(jar, "jar content");

        var result = await ModFileInstaller.ImportLocalModAsync(_modsDir, jar, TestContext.Current.CancellationToken);

        Assert.True(result.Completed);
        Assert.Equal("jar content", File.ReadAllText(jar));
        Assert.Single(Directory.GetFiles(_modsDir));
    }

    [Fact]
    public async Task ImportLocalModAsync_NonJarFile_Rejects()
    {
        string textFile = Path.Combine(_testDir, "test.txt");
        File.WriteAllText(textFile, "not a jar");

        var result = await ModFileInstaller.ImportLocalModAsync(_modsDir, textFile, TestContext.Current.CancellationToken);
        Assert.True(result.Failed);
    }

    [Fact]
    public async Task ImportLocalModAsync_JarFile_Copies()
    {
        string jarFile = Path.Combine(_testDir, "imported.jar");
        File.WriteAllText(jarFile, "jar content");

        var result = await ModFileInstaller.ImportLocalModAsync(_modsDir, jarFile, TestContext.Current.CancellationToken);
        Assert.True(result.Completed);
        Assert.True(File.Exists(Path.Combine(_modsDir, "imported.jar")));
        Assert.Single(Directory.GetFiles(_modsDir));
    }

    private const string ValidContent = "downloaded content";
    private static readonly string ValidSha512 = Infrastructure.Utilities.HashCalculator.DigestBytes(
        System.Text.Encoding.UTF8.GetBytes(ValidContent),
        "sha512");

    [Fact]
    public async Task InstallRemoteModAsync_DownloadFails_RollsBack()
    {
        var fakeHttp = StubHttpPort.WithDownloadFailure("網路連線失敗");
        var installer = new ModFileInstaller(fakeHttp);

        var result = await installer.InstallRemoteModAsync(
            _modsDir,
            "https://cdn.modrinth.com/data/ABC/versions/1.0/fail.jar",
            "fail.jar",
            ValidSha512,
            "sha512",
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Failed);
        Assert.False(File.Exists(Path.Combine(_modsDir, "fail.jar")));
    }

    [Theory]
    [InlineData("https://example.invalid/mod.jar", "abcdef")]
    [InlineData("https://cdn.modrinth.com/data/ABC/versions/1.0/mod.jar", "")]
    [InlineData("https://cdn.modrinth.com/data/ABC/versions/1.0/mod.jar", null)]
    public async Task InstallRemoteModAsync_UnofficialUrlOrMissingHash_Rejects(string url, string? expectedHash)
    {
        var installer = new ModFileInstaller(StubHttpPort.WithDownloadContent("downloaded content"));

        var result = await installer.InstallRemoteModAsync(_modsDir, url, "mod.jar", expectedHash, "sha512", cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Failed);
        Assert.False(File.Exists(Path.Combine(_modsDir, "mod.jar")));
    }

    [Fact]
    public async Task InstallRemoteModAsync_ConcurrentDownloads_UseIsolatedStaging()
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
            installer.InstallRemoteModAsync(_modsDir, "https://cdn.modrinth.com/data/A/versions/1/first.jar", "first.jar", ValidSha512, "sha512", cancellationToken: TestContext.Current.CancellationToken),
            installer.InstallRemoteModAsync(_modsDir, "https://cdn.modrinth.com/data/B/versions/1/second.jar", "second.jar", ValidSha512, "sha512", cancellationToken: TestContext.Current.CancellationToken));

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
    [InlineData("https://cdn.modrinth.com:8443/mod.jar", false)]
    [InlineData("https://user:pass@cdn.modrinth.com/mod.jar", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    [InlineData("not a url", false)]
    public void IsOfficialModrinthSource_VariousUrls_ValidatesHost(string? url, bool expected)
    {
        bool actual = ModFileInstaller.IsOfficialModrinthSource(url);
        Assert.Equal(expected, actual);
    }
}
