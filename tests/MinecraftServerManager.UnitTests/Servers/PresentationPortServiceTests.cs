using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class PresentationPortServiceTests : IDisposable
{
    private readonly TempDirectory _rootTemp = new("msm-ports-");
    private readonly string _root;
    private readonly string _serversRoot;
    private readonly string _externalDir;

    public PresentationPortServiceTests()
    {
        _root = _rootTemp.FullName;
        _serversRoot = Path.Combine(_root, "servers");
        _externalDir = Path.Combine(_root, "external-backups");
        Directory.CreateDirectory(_serversRoot);
    }

    public void Dispose() => _rootTemp.Dispose();

    [Fact]
    public async Task LocalFileSystem_Paths_ReportsExistenceAndCreates()
    {
        ILocalFileSystem fs = new LocalFileSystem();
        string dir = Path.Combine(_root, "created");
        string file = Path.Combine(_root, "a.txt");
        File.WriteAllText(file, "x");

        Assert.False(await fs.DirectoryExistsAsync(dir, TestContext.Current.CancellationToken));
        Assert.Null(await fs.GetDirectoryLastWriteTimeAsync(dir, TestContext.Current.CancellationToken));
        await fs.CreateDirectoryAsync(dir, TestContext.Current.CancellationToken);

        Assert.True(await fs.DirectoryExistsAsync(dir, TestContext.Current.CancellationToken));
        Assert.NotNull(await fs.GetDirectoryLastWriteTimeAsync(dir, TestContext.Current.CancellationToken));
        Assert.True(await fs.FileExistsAsync(file, TestContext.Current.CancellationToken));
        Assert.False(await fs.FileExistsAsync(null, TestContext.Current.CancellationToken));
        Assert.False(await fs.DirectoryExistsAsync("   ", TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task ModFileService_EnabledDisabledMissing_ResolvesPaths()
    {
        IModFileService service = new ModFileService();
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        string modsDir = await service.EnsureModsDirectoryAsync(serverDir, TestContext.Current.CancellationToken);
        File.WriteAllText(Path.Combine(modsDir, "enabled.jar"), "x");
        File.WriteAllText(Path.Combine(modsDir, "off.jar.disabled"), "x");

        Assert.True(Directory.Exists(modsDir));
        Assert.Equal(Path.Combine(modsDir, "enabled.jar"), await service.ResolveModFilePathAsync(serverDir, "enabled.jar", TestContext.Current.CancellationToken));
        Assert.Equal(Path.Combine(modsDir, "off.jar.disabled"), await service.ResolveModFilePathAsync(serverDir, "off.jar", TestContext.Current.CancellationToken));
        Assert.Equal(Path.Combine(serverDir, "mods"), await service.ResolveModFilePathAsync(serverDir, "missing.jar", TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task ModFileService_DeleteOutsideModsDirectory_Ignores()
    {
        IModFileService service = new ModFileService();
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        await service.EnsureModsDirectoryAsync(serverDir, TestContext.Current.CancellationToken);
        string outside = Path.Combine(serverDir, "server.jar");
        File.WriteAllText(outside, "x");

        await service.DeleteModFileVariantsAsync(serverDir, @"..\server.jar", TestContext.Current.CancellationToken);
        await service.DeleteModFileVariantsAsync(serverDir, "notes.txt", TestContext.Current.CancellationToken);

        Assert.True(File.Exists(outside));
    }

    [Fact]
    public async Task ModFileService_DeleteBothVariants_CleansStaging()
    {
        IModFileService service = new ModFileService();
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        string modsDir = await service.EnsureModsDirectoryAsync(serverDir, TestContext.Current.CancellationToken);
        File.WriteAllText(Path.Combine(modsDir, "old.jar"), "x");
        File.WriteAllText(Path.Combine(modsDir, "old.jar.disabled"), "x");
        File.WriteAllText(Path.Combine(modsDir, "keep.jar"), "x");
        string staging = Path.Combine(modsDir, ".download_staging");
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(staging, "partial.tmp"), "x");

        await service.DeleteModFileVariantsAsync(serverDir, "old.jar", TestContext.Current.CancellationToken);
        await service.CleanupStagingDirectoryAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.False(File.Exists(Path.Combine(modsDir, "old.jar")));
        Assert.False(File.Exists(Path.Combine(modsDir, "old.jar.disabled")));
        Assert.True(File.Exists(Path.Combine(modsDir, "keep.jar")));
        Assert.False(Directory.Exists(staging));
    }

    [Theory]
    [InlineData("https://cdn.modrinth.com/data/abc/versions/1/mod.jar", true)]
    [InlineData("https://example.com/mod.jar", false)]
    [InlineData(null, false)]
    public void ModFileService_OfficialSourceCheck_Delegates(string? url, bool expected)
    {
        IModFileService service = new ModFileService();

        Assert.Equal(expected, service.IsOfficialModrinthSource(url));
    }

    [Fact]
    public async Task ServersRootService_Operations_ValidatesProbesAndRelocates()
    {
        IServersRootService service = new ServersRootService();
        string serverDir = Path.Combine(_serversRoot, "Alpha");
        Directory.CreateDirectory(serverDir);
        await File.WriteAllTextAsync(Path.Combine(serverDir, "server.jar"), "jar", TestContext.Current.CancellationToken);
        string newParent = Path.Combine(_root, "new-location");

        var check = await service.ValidateTargetRootAsync(_serversRoot, newParent, TestContext.Current.CancellationToken);

        Assert.Equal(RelocationPathCheckResult.Valid, check.Result);
        Assert.Equal(Path.Combine(newParent, "servers"), check.NormalizedNew);
        Assert.True(await service.HasStoredContentAsync(check.NormalizedCurrent, TestContext.Current.CancellationToken));
        Assert.True(await service.IsTargetDirectoryEmptyAsync(check.NormalizedNew, TestContext.Current.CancellationToken));

        await service.RelocateAllContentAsync(check.NormalizedCurrent, check.NormalizedNew, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(File.Exists(Path.Combine(check.NormalizedNew, "Alpha", "server.jar")));
    }

    [Fact]
    public async Task ServersRootService_SameRoot_Detects()
    {
        IServersRootService service = new ServersRootService();

        var check = await service.ValidateTargetRootAsync(_serversRoot, _root, TestContext.Current.CancellationToken);

        Assert.Equal(RelocationPathCheckResult.SameAsCurrent, check.Result);
    }

    [Fact]
    public async Task BackupSummary_VariousStates_ReportsStatus()
    {
        IServerBackupService service = new ServerBackupService(_serversRoot, static () => 10, TimeProvider.System);

        Assert.Equal(ServerBackupSummaryStatus.NotConfigured, (await service.GetBackupSummaryAsync("Alpha", null, TestContext.Current.CancellationToken)).Status);
        Assert.Equal(
            ServerBackupSummaryStatus.DirectoryMissing,
            (await service.GetBackupSummaryAsync("Alpha", _externalDir, TestContext.Current.CancellationToken)).Status);

        Directory.CreateDirectory(_externalDir);
        Assert.Equal(ServerBackupSummaryStatus.NoBackups, (await service.GetBackupSummaryAsync("Alpha", _externalDir, TestContext.Current.CancellationToken)).Status);

        File.WriteAllText(Path.Combine(_externalDir, "backup-Alpha-20260101-000000.zip"), "z");
        File.WriteAllText(Path.Combine(_externalDir, "Alpha.zip"), "z");
        File.WriteAllText(Path.Combine(_externalDir, "backup-Beta-20260101-000000.zip"), "z");

        var summary = await service.GetBackupSummaryAsync("Alpha", _externalDir, TestContext.Current.CancellationToken);
        Assert.Equal(ServerBackupSummaryStatus.HasBackups, summary.Status);
        Assert.Equal(2, summary.Count);
        Assert.NotNull(summary.LatestWriteTime);
    }

    [Fact]
    public async Task BackupDestination_InsideServersRoot_Rejects()
    {
        IServerBackupService service = new ServerBackupService(_serversRoot, static () => 10, TimeProvider.System);

        Assert.NotNull(await service.ValidateBackupDestinationAsync(Path.Combine(_serversRoot, "Alpha", "backups"), TestContext.Current.CancellationToken));
        Assert.NotNull(await service.ValidateBackupDestinationAsync(Path.Combine(_serversRoot, "a.zip"), TestContext.Current.CancellationToken));
        Assert.Null(await service.ValidateBackupDestinationAsync(_externalDir, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task PrepareBackupFilePath_NewBackup_CreatesTimestampedPath()
    {
        IServerBackupService service = new ServerBackupService(_serversRoot, static () => 10, TimeProvider.System);

        string path = await service.PrepareBackupFilePathAsync("Alpha", _externalDir, TestContext.Current.CancellationToken);

        Assert.True(Directory.Exists(_externalDir));
        Assert.Equal(_externalDir, Path.GetDirectoryName(path));
        Assert.StartsWith("backup-Alpha-", Path.GetFileName(path), StringComparison.Ordinal);
        Assert.EndsWith(".zip", path, StringComparison.Ordinal);
    }
}
