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

    [Fact]
    public async Task SupportsExternalBackupDirectoryForListRestoreAndDelete()
    {
        string externalDir = Path.Combine(Path.GetTempPath(), "msm-external-backups-" + Guid.NewGuid().ToString("N"));
        try
        {
            var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: externalDir);
            Assert.True(File.Exists(backup.FullPath));
            Assert.StartsWith(Path.GetFullPath(externalDir), backup.FullPath, StringComparison.OrdinalIgnoreCase);

            var listed = await _backupService.ListBackupsAsync("TestServer", externalDir);
            Assert.Single(listed);
            Assert.Equal(backup.FileName, listed[0].FileName);

            File.WriteAllText(Path.Combine(_serverDir, "server.properties"), "motd=Modified Content");
            bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName, externalDir);
            Assert.True(restored);
            Assert.Equal("motd=Initial Server", File.ReadAllText(Path.Combine(_serverDir, "server.properties")));

            bool deleted = await _backupService.DeleteBackupAsync("TestServer", backup.FileName, externalDir);
            Assert.True(deleted);
            Assert.False(File.Exists(backup.FullPath));
        }
        finally
        {
            try
            {
                if (Directory.Exists(externalDir))
                {
                    Directory.Delete(externalDir, recursive: true);
                }
            }
            catch
            {
            }
        }
    }

    [Fact]
    public async Task RejectsBackupDirectoryInsideServersRoot()
    {
        string invalidDir = Path.Combine(_testRoot, "InvalidInsideBackupDir");
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            _backupService.CreateBackupAsync("TestServer", destinationPath: invalidDir));
    }

    [Fact]
    public async Task RestoresBackup_PreservesLiveDiagnosticsAndCrashReports()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer");

        // 模擬伺服器運行後產生了崩潰報告與現場最新日誌
        string logsDir = Path.Combine(_serverDir, "logs");
        string crashDir = Path.Combine(_serverDir, "crash-reports");
        Directory.CreateDirectory(logsDir);
        Directory.CreateDirectory(crashDir);

        File.WriteAllText(Path.Combine(logsDir, "latest.log"), "Live latest log before disaster");
        File.WriteAllText(Path.Combine(crashDir, "crash-2026-09-24.txt"), "Live crash traceback");

        bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName);
        Assert.True(restored);

        // 驗證崩潰報告被妥善保留移回
        Assert.True(File.Exists(Path.Combine(crashDir, "crash-2026-09-24.txt")));
        Assert.Equal("Live crash traceback", File.ReadAllText(Path.Combine(crashDir, "crash-2026-09-24.txt")));

        // 驗證現場日誌被保留
        bool hasLog = File.Exists(Path.Combine(logsDir, "latest.log")) || File.Exists(Path.Combine(logsDir, "latest.log.pre-restore"));
        Assert.True(hasLog);
    }
}
