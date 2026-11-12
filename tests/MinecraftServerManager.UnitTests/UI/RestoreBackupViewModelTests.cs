using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class RestoreBackupViewModelTests
{
    [Fact]
    public async Task RefreshBackupsAsync_PopulatesBackupsCorrectly()
    {
        var backupService = new FakeBackupService([
            new ServerBackupInfo("backup_2026.zip", "/backups/backup_2026.zip", 1024 * 1024, DateTimeOffset.UtcNow)
        ]);

        var vm = new RestoreBackupViewModel(backupService, "TestServer", NoOpUiService.Instance, "/backups", static () => false);
        await vm.RefreshBackupsAsync();

        var item = Assert.Single(vm.Backups);
        Assert.Equal("backup_2026.zip", item.FileName);
    }

    [Theory]
    [InlineData(true, false)]
    [InlineData(false, true)]
    public async Task RestoreAsync_HonorsServerRunningState(bool isRunning, bool expectedRestored)
    {
        var backupService = new FakeBackupService([
            new ServerBackupInfo("backup_2026.zip", "/backups/backup_2026.zip", 1024 * 1024, DateTimeOffset.UtcNow)
        ]);

        var vm = new RestoreBackupViewModel(
            backupService,
            "TestServer",
            NoOpUiService.Instance,
            "/backups",
            isServerRunningCheck: () => isRunning);

        await vm.RefreshBackupsAsync();
        vm.SelectedBackup = vm.Backups[0];

        await vm.RestoreAsync();

        Assert.Equal(expectedRestored, backupService.RestoreCalled);
        if (isRunning)
        {
            Assert.Contains("伺服器正在執行中", vm.StatusMessage);
        }
    }

    private sealed class FakeBackupService(IReadOnlyList<ServerBackupInfo> backups) : IServerBackupService
    {
        public bool RestoreCalled { get; private set; }

        public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(
            string serverName,
            string? backupDirectory = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(backups);

        public Task<ServerBackupInfo> CreateBackupAsync(
            string serverName,
            string? destinationPath = null,
            string? comment = null,
            IProgress<ServerBackupProgressReport>? progress = null,
            CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<bool> RestoreBackupAsync(
            string serverName,
            string backupFileName,
            string? backupDirectory = null,
            IProgress<ServerBackupProgressReport>? progress = null,
            CancellationToken cancellationToken = default)
        {
            RestoreCalled = true;
            return Task.FromResult(true);
        }

        public Task<bool> DeleteBackupAsync(
            string serverName,
            string backupFileName,
            string? backupDirectory = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(true);

        public ServerBackupSummary GetBackupSummary(string serverName, string? backupDirectory) =>
            new(ServerBackupSummaryStatus.HasBackups, backups.Count);

        public string? ValidateBackupDestination(string destinationPath) => null;

        public string PrepareBackupFilePath(string serverName, string destinationDirectory) =>
            Path.Combine(destinationDirectory, $"backup-{serverName}.zip");
    }
}
