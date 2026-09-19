using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerBackupServiceTests : IDisposable
{
    private readonly string _testRoot;
    private readonly string _serverDir;
    private readonly ServerBackupService _backupService;

    public ServerBackupServiceTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-backup-tests-" + Guid.NewGuid().ToString("N"));
        _serverDir = Path.Combine(_testRoot, "TestServer");
        Directory.CreateDirectory(_serverDir);

        File.WriteAllText(Path.Combine(_serverDir, "server.properties"), "motd=Initial Server");
        File.WriteAllText(Path.Combine(_serverDir, "world.txt"), "world-data");

        _backupService = new ServerBackupService(_testRoot);
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
    public async Task CreatesAndListsBackupsSuccessfully()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer", comment: "Test Backup 1");

        Assert.NotNull(backup);
        Assert.True(File.Exists(backup.FullPath));
        Assert.True(backup.SizeBytes > 0);

        var list = await _backupService.ListBackupsAsync("TestServer");
        Assert.Single(list);
        Assert.Equal(backup.FileName, list[0].FileName);
    }

    [Fact]
    public async Task RestoresBackupOverExistingFiles()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer");

        // 修改原始檔案
        File.WriteAllText(Path.Combine(_serverDir, "server.properties"), "motd=Modified Content");
        File.Delete(Path.Combine(_serverDir, "world.txt"));

        bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName);
        Assert.True(restored);

        Assert.True(File.Exists(Path.Combine(_serverDir, "world.txt")));
        Assert.Equal("motd=Initial Server", File.ReadAllText(Path.Combine(_serverDir, "server.properties")));
    }

    [Fact]
    public async Task DeletesBackupSuccessfully()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer");
        Assert.True(File.Exists(backup.FullPath));

        bool deleted = await _backupService.DeleteBackupAsync("TestServer", backup.FileName);
        Assert.True(deleted);
        Assert.False(File.Exists(backup.FullPath));

        var list = await _backupService.ListBackupsAsync("TestServer");
        Assert.Empty(list);
    }
}
