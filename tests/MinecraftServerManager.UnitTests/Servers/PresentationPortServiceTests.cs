using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

/// <summary>呈現層連接埠實作測試：LocalFileSystem、ModFileService、ServersRootService 與備份摘要／目的地驗證</summary>
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
    public void LocalFileSystem_ReportsExistenceAndCreatesDirectories()
    {
        ILocalFileSystem fs = new LocalFileSystem();
        string dir = Path.Combine(_root, "created");
        string file = Path.Combine(_root, "a.txt");
        File.WriteAllText(file, "x");

        Assert.False(fs.DirectoryExists(dir));
        Assert.Null(fs.GetDirectoryLastWriteTime(dir));
        fs.CreateDirectory(dir);

        Assert.True(fs.DirectoryExists(dir));
        Assert.NotNull(fs.GetDirectoryLastWriteTime(dir));
        Assert.True(fs.FileExists(file));
        Assert.False(fs.FileExists(null));
        Assert.False(fs.DirectoryExists("   "));
    }

    [Fact]
    public void ModFileService_ResolvesEnabledDisabledAndMissingFiles()
    {
        IModFileService service = new ModFileService();
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        string modsDir = service.EnsureModsDirectory(serverDir);
        File.WriteAllText(Path.Combine(modsDir, "enabled.jar"), "x");
        File.WriteAllText(Path.Combine(modsDir, "off.jar.disabled"), "x");

        Assert.True(Directory.Exists(modsDir));
        Assert.Equal(Path.Combine(modsDir, "enabled.jar"), service.ResolveModFilePath(serverDir, "enabled.jar"));
        Assert.Equal(Path.Combine(modsDir, "off.jar.disabled"), service.ResolveModFilePath(serverDir, "off.jar"));
        Assert.Equal(Path.Combine(serverDir, "mods"), service.ResolveModFilePath(serverDir, "missing.jar"));
    }

    [Fact]
    public void ModFileService_DeletesBothVariantsAndCleansStaging()
    {
        IModFileService service = new ModFileService();
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        string modsDir = service.EnsureModsDirectory(serverDir);
        File.WriteAllText(Path.Combine(modsDir, "old.jar"), "x");
        File.WriteAllText(Path.Combine(modsDir, "old.jar.disabled"), "x");
        File.WriteAllText(Path.Combine(modsDir, "keep.jar"), "x");
        string staging = Path.Combine(modsDir, ".download_staging");
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(staging, "partial.tmp"), "x");

        service.DeleteModFileVariants(serverDir, "old.jar");
        service.CleanupStagingDirectory(serverDir);

        Assert.False(File.Exists(Path.Combine(modsDir, "old.jar")));
        Assert.False(File.Exists(Path.Combine(modsDir, "old.jar.disabled")));
        Assert.True(File.Exists(Path.Combine(modsDir, "keep.jar")));
        Assert.False(Directory.Exists(staging));
    }

    [Theory]
    [InlineData("https://cdn.modrinth.com/data/abc/versions/1/mod.jar", true)]
    [InlineData("https://example.com/mod.jar", false)]
    [InlineData(null, false)]
    public void ModFileService_DelegatesOfficialSourceCheck(string? url, bool expected)
    {
        IModFileService service = new ModFileService();

        Assert.Equal(expected, service.IsOfficialModrinthSource(url));
    }

    [Fact]
    public async Task ServersRootService_ValidatesProbesAndRelocates()
    {
        IServersRootService service = new ServersRootService();
        string serverDir = Path.Combine(_serversRoot, "Alpha");
        Directory.CreateDirectory(serverDir);
        await File.WriteAllTextAsync(Path.Combine(serverDir, "server.jar"), "jar");
        string newParent = Path.Combine(_root, "new-location");

        var check = service.ValidateTargetRoot(_serversRoot, newParent);

        Assert.Equal(RelocationPathCheckResult.Valid, check.Result);
        Assert.Equal(Path.Combine(newParent, "servers"), check.NormalizedNew);
        Assert.True(await service.HasStoredContentAsync(check.NormalizedCurrent));
        Assert.True(await service.IsTargetDirectoryEmptyAsync(check.NormalizedNew));

        await service.RelocateAllContentAsync(check.NormalizedCurrent, check.NormalizedNew);

        Assert.True(File.Exists(Path.Combine(check.NormalizedNew, "Alpha", "server.jar")));
    }

    [Fact]
    public void ServersRootService_DetectsSameRoot()
    {
        IServersRootService service = new ServersRootService();

        var check = service.ValidateTargetRoot(_serversRoot, _root);

        Assert.Equal(RelocationPathCheckResult.SameAsCurrent, check.Result);
    }

    [Fact]
    public void BackupSummary_ReportsNotConfiguredMissingEmptyAndCounts()
    {
        IServerBackupService service = new ServerBackupService(_serversRoot, static () => 10);

        Assert.Equal(ServerBackupSummaryStatus.NotConfigured, service.GetBackupSummary("Alpha", null).Status);
        Assert.Equal(ServerBackupSummaryStatus.DirectoryMissing, service.GetBackupSummary("Alpha", _externalDir).Status);

        Directory.CreateDirectory(_externalDir);
        Assert.Equal(ServerBackupSummaryStatus.NoBackups, service.GetBackupSummary("Alpha", _externalDir).Status);

        File.WriteAllText(Path.Combine(_externalDir, "backup-Alpha-20260101-000000.zip"), "z");
        File.WriteAllText(Path.Combine(_externalDir, "Alpha.zip"), "z");
        File.WriteAllText(Path.Combine(_externalDir, "backup-Beta-20260101-000000.zip"), "z");

        var summary = service.GetBackupSummary("Alpha", _externalDir);
        Assert.Equal(ServerBackupSummaryStatus.HasBackups, summary.Status);
        Assert.Equal(2, summary.Count);
        Assert.NotNull(summary.LatestWriteTime);
    }

    [Fact]
    public void BackupDestination_RejectsPathsInsideServersRoot()
    {
        IServerBackupService service = new ServerBackupService(_serversRoot, static () => 10);

        Assert.NotNull(service.ValidateBackupDestination(Path.Combine(_serversRoot, "Alpha", "backups")));
        Assert.NotNull(service.ValidateBackupDestination(Path.Combine(_serversRoot, "a.zip")));
        Assert.Null(service.ValidateBackupDestination(_externalDir));
    }

    [Fact]
    public void PrepareBackupFilePath_CreatesDirectoryAndTimestampedName()
    {
        IServerBackupService service = new ServerBackupService(_serversRoot, static () => 10);

        string path = service.PrepareBackupFilePath("Alpha", _externalDir);

        Assert.True(Directory.Exists(_externalDir));
        Assert.Equal(_externalDir, Path.GetDirectoryName(path));
        Assert.StartsWith("backup-Alpha-", Path.GetFileName(path), StringComparison.Ordinal);
        Assert.EndsWith(".zip", path, StringComparison.Ordinal);
    }
}
