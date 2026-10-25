using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerBackupServiceTests : IDisposable
{
    private readonly string _testRoot;
    private readonly string _serverDir;
    private readonly string _externalBackupsDir;
    private readonly ServerBackupService _backupService;

    public ServerBackupServiceTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-backup-tests-" + Guid.NewGuid().ToString("N"));
        _serverDir = Path.Combine(_testRoot, "TestServer");
        _externalBackupsDir = Path.Combine(Path.GetTempPath(), "msm-backup-ext-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_serverDir);
        Directory.CreateDirectory(_externalBackupsDir);

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
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }

        try
        {
            if (Directory.Exists(_externalBackupsDir))
            {
                Directory.Delete(_externalBackupsDir, recursive: true);
            }
        }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
    }

    [Fact]
    public async Task RejectsCreateBackupWithoutDestinationPath()
    {
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            _backupService.CreateBackupAsync("TestServer", destinationPath: null));

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            _backupService.CreateBackupAsync("TestServer", destinationPath: "   "));
    }

    [Fact]
    public async Task CreatesAndListsBackupsSuccessfully()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir, comment: "Test Backup 1");

        Assert.NotNull(backup);
        Assert.True(File.Exists(backup.FullPath));
        Assert.True(backup.SizeBytes > 0);

        var list = await _backupService.ListBackupsAsync("TestServer", _externalBackupsDir);
        var item = Assert.Single(list);
        Assert.Equal(backup.FileName, item.FileName);
    }

    [Fact]
    public async Task RestoresBackupOverExistingFiles()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);

        // 修改原始檔案
        File.WriteAllText(Path.Combine(_serverDir, "server.properties"), "motd=Modified Content");
        File.Delete(Path.Combine(_serverDir, "world.txt"));

        bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName, _externalBackupsDir);
        Assert.True(restored);

        Assert.True(File.Exists(Path.Combine(_serverDir, "world.txt")));
        Assert.Equal("motd=Initial Server", File.ReadAllText(Path.Combine(_serverDir, "server.properties")));
    }

    [Fact]
    public async Task DeletesBackupSuccessfully()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);
        Assert.True(File.Exists(backup.FullPath));

        bool deleted = await _backupService.DeleteBackupAsync("TestServer", backup.FileName, _externalBackupsDir);
        Assert.True(deleted);
        Assert.False(File.Exists(backup.FullPath));

        var list = await _backupService.ListBackupsAsync("TestServer", _externalBackupsDir);
        Assert.Empty(list);
    }

    [Fact]
    public async Task SupportsExternalBackupDirectoryForListRestoreAndDelete()
    {
        string extraDir = Path.Combine(Path.GetTempPath(), "msm-extra-backups-" + Guid.NewGuid().ToString("N"));
        try
        {
            var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: extraDir);
            Assert.True(File.Exists(backup.FullPath));
            Assert.StartsWith(Path.GetFullPath(extraDir), backup.FullPath, StringComparison.OrdinalIgnoreCase);

            var listed = await _backupService.ListBackupsAsync("TestServer", extraDir);
            var item = Assert.Single(listed);
            Assert.Equal(backup.FileName, item.FileName);

            File.WriteAllText(Path.Combine(_serverDir, "server.properties"), "motd=Modified Content");
            bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName, extraDir);
            Assert.True(restored);
            Assert.Equal("motd=Initial Server", File.ReadAllText(Path.Combine(_serverDir, "server.properties")));

            bool deleted = await _backupService.DeleteBackupAsync("TestServer", backup.FileName, extraDir);
            Assert.True(deleted);
            Assert.False(File.Exists(backup.FullPath));
        }
        finally
        {
            try
            {
                if (Directory.Exists(extraDir))
                {
                    Directory.Delete(extraDir, recursive: true);
                }
            }
            catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
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
        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);

        // 模擬伺服器運作後產生了當機報告與現場最新記錄檔
        string logsDir = Path.Combine(_serverDir, "logs");
        string crashDir = Path.Combine(_serverDir, "crash-reports");
        Directory.CreateDirectory(logsDir);
        Directory.CreateDirectory(crashDir);

        File.WriteAllText(Path.Combine(logsDir, "latest.log"), "Live latest log before disaster");
        File.WriteAllText(Path.Combine(crashDir, "crash-2026-09-24.txt"), "Live crash traceback");

        bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName, _externalBackupsDir);
        Assert.True(restored);

        // 驗證當機報告被妥善保留移回
        Assert.True(File.Exists(Path.Combine(crashDir, "crash-2026-09-24.txt")));
        Assert.Equal("Live crash traceback", File.ReadAllText(Path.Combine(crashDir, "crash-2026-09-24.txt")));

        // 驗證現場記錄檔被保留
        bool hasLog = File.Exists(Path.Combine(logsDir, "latest.log")) || File.Exists(Path.Combine(logsDir, "latest.log.pre-restore"));
        Assert.True(hasLog);
    }

    [Fact]
    public async Task RestoresBackup_ClearsReadOnlyAttribute_SuccessfullyRestores()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);

        // 將既有檔案設為 ReadOnly 唯讀屬性，模擬鎖定情況
        string propsPath = Path.Combine(_serverDir, "server.properties");
        File.SetAttributes(propsPath, FileAttributes.ReadOnly);

        bool restored = await _backupService.RestoreBackupAsync("TestServer", backup.FileName, _externalBackupsDir);
        Assert.True(restored);

        // 還原後唯讀屬性應被清除且內容成功復原
        var attrs = File.GetAttributes(propsPath);
        Assert.False(attrs.HasFlag(FileAttributes.ReadOnly));
        Assert.Equal("motd=Initial Server", File.ReadAllText(propsPath));
    }

    [Fact]
    public async Task CreateBackupAsync_PrunesAndExcludesDiagnosticDirectories()
    {
        // 建立伺服器診斷與記錄資料夾
        string logsDir = Path.Combine(_serverDir, "logs");
        string crashDir = Path.Combine(_serverDir, "crash-reports");
        string legacyBackupsDir = Path.Combine(_serverDir, "backups");
        Directory.CreateDirectory(logsDir);
        Directory.CreateDirectory(crashDir);
        Directory.CreateDirectory(legacyBackupsDir);

        File.WriteAllText(Path.Combine(logsDir, "latest.log"), "diagnostic log");
        File.WriteAllText(Path.Combine(crashDir, "crash.txt"), "crash report");
        File.WriteAllText(Path.Combine(legacyBackupsDir, "old-backup.zip"), "old zip");

        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);
        string backupFile = Path.Combine(_externalBackupsDir, backup.FileName);

        Assert.True(File.Exists(backupFile));

        using var archive = Infrastructure.FileSystem.SafeZipArchive.OpenRead(backupFile);
        var entryNames = archive.Entries.Select(static e => e.FullName).ToList();

        // 必須包含正常伺服器設定
        Assert.Contains(entryNames, static n => n.Equals("server.properties", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(entryNames, static n => n.Equals("world.txt", StringComparison.OrdinalIgnoreCase));

        // 必須排除 logs、crash-reports 與舊版 backups
        Assert.DoesNotContain(entryNames, static n => n.StartsWith("logs/", StringComparison.OrdinalIgnoreCase) || n.StartsWith("logs\\", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(entryNames, static n => n.StartsWith("crash-reports/", StringComparison.OrdinalIgnoreCase) || n.StartsWith("crash-reports\\", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(entryNames, static n => n.StartsWith("backups/", StringComparison.OrdinalIgnoreCase) || n.StartsWith("backups\\", StringComparison.OrdinalIgnoreCase));
    }
}
