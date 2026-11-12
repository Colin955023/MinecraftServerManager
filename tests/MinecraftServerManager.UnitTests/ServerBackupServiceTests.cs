using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed partial class ServerBackupServiceTests : IDisposable
{
    private readonly TempDirectory _root = new("msm-backup-tests-");
    private readonly TempDirectory _external = new("msm-backup-ext-");
    private readonly string _testRoot;
    private readonly string _serverDir;
    private readonly string _externalBackupsDir;
    private readonly ServerBackupService _backupService;

    public ServerBackupServiceTests()
    {
        _testRoot = _root.FullName;
        _serverDir = Path.Combine(_testRoot, "TestServer");
        _externalBackupsDir = _external.FullName;
        Directory.CreateDirectory(_serverDir);

        File.WriteAllText(Path.Combine(_serverDir, "server.properties"), "motd=Initial Server");
        File.WriteAllText(Path.Combine(_serverDir, "world.txt"), "world-data");

        _backupService = new ServerBackupService(_testRoot, static () => 10);
    }

    public void Dispose()
    {
        _root.Dispose();
        _external.Dispose();
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
        using var extra = new TempDirectory("msm-extra-backups-");
        string extraDir = Path.Combine(extra.FullName, "backups");
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

        // 備份建立於無 logs 時，現場記錄檔應原位保留（不產生 .pre-restore）
        Assert.Equal("Live latest log before disaster", File.ReadAllText(Path.Combine(logsDir, "latest.log")));
        Assert.False(File.Exists(Path.Combine(logsDir, "latest.log.pre-restore")));
        Assert.Equal("world-data", File.ReadAllText(Path.Combine(_serverDir, "world.txt")));
    }

    [Fact]
    public async Task RestoresBackup_WhenBackupContainsLatestLog_KeepsBothAsPreRestore()
    {
        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);

        // 備份本身預設不含 logs；手動加入 logs/latest.log 模擬舊版備份，使其與現場記錄檔衝突
        string backupPath = Path.Combine(_externalBackupsDir, backup.FileName);
        using (var zipStream = new FileStream(backupPath, FileMode.Open, FileAccess.ReadWrite))
        using (var archive = new System.IO.Compression.ZipArchive(zipStream, System.IO.Compression.ZipArchiveMode.Update))
        using (var writer = new StreamWriter(archive.CreateEntry("logs/latest.log").Open()))
        {
            writer.Write("Log inside backup");
        }

        string logsDir = Path.Combine(_serverDir, "logs");
        Directory.CreateDirectory(logsDir);
        File.WriteAllText(Path.Combine(logsDir, "latest.log"), "Live latest log before disaster");

        Assert.True(await _backupService.RestoreBackupAsync("TestServer", backup.FileName, _externalBackupsDir));

        Assert.Equal("Log inside backup", File.ReadAllText(Path.Combine(logsDir, "latest.log")));
        Assert.Equal("Live latest log before disaster", File.ReadAllText(Path.Combine(logsDir, "latest.log.pre-restore")));
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

    [Fact]
    public async Task CreateBackupAsync_KeepsNestedFoldersNamedLikeExcludedDirectories()
    {
        string pluginBackups = Path.Combine(_serverDir, "plugins", "CoreProtect", "backups");
        string configLogs = Path.Combine(_serverDir, "config", "mod", "logs");
        Directory.CreateDirectory(pluginBackups);
        Directory.CreateDirectory(configLogs);
        File.WriteAllText(Path.Combine(pluginBackups, "data.db"), "plugin data");
        File.WriteAllText(Path.Combine(configLogs, "settings.json"), "{}");

        var backup = await _backupService.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);

        using var archive = Infrastructure.FileSystem.SafeZipArchive.OpenRead(Path.Combine(_externalBackupsDir, backup.FileName));
        var entryNames = archive.Entries.Select(static e => e.FullName.Replace('\\', '/')).ToList();
        Assert.Contains("plugins/CoreProtect/backups/data.db", entryNames, StringComparer.OrdinalIgnoreCase);
        Assert.Contains("config/mod/logs/settings.json", entryNames, StringComparer.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("a", "backup-a-20260101-120000.zip", true)]
    [InlineData("a", "backup-a-20260101-120000-1a2b3c.zip", true)]
    [InlineData("a", "a-20260101-120000.zip", true)]
    [InlineData("a", "backup-a.zip", true)]
    [InlineData("a", "a.zip", true)]
    [InlineData("A", "backup-a-20260101-120000.zip", true)]
    [InlineData("a", "backup-a-b-20260101-120000.zip", false)]
    [InlineData("a", "a-b-20260101-120000.zip", false)]
    [InlineData("a", "backup-ab.zip", false)]
    public void IsBackupFileFor_MatchesOnlyTimestampedOwnBackups(string serverName, string fileName, bool expected) => Assert.Equal(expected, ServerBackupService.IsBackupFileFor(serverName, fileName));

    [Fact]
    public async Task RetentionCountIsReadDynamicallyFromProvider()
    {
        int retention = 3;
        var service = new ServerBackupService(_testRoot, () => retention);

        for (int i = 0; i < 4; i++)
        {
            await service.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);
        }

        Assert.Equal(3, (await service.ListBackupsAsync("TestServer", _externalBackupsDir)).Count);

        retention = 1;
        await service.CreateBackupAsync("TestServer", destinationPath: _externalBackupsDir);

        Assert.Single(await service.ListBackupsAsync("TestServer", _externalBackupsDir));
    }
}
