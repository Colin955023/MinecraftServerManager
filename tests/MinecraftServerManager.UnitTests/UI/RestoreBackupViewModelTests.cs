using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class RestoreBackupViewModelTests
{
    [Fact]
    public async Task RefreshBackupsAsync_BackupsExist_PopulatesList()
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
    public async Task RestoreAsync_ServerRunning_Blocks(bool isRunning, bool expectedRestored)
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

    [Fact]
    public async Task RefreshBackupsAsync_EmptyList_ClearsSelectionAndDisablesCommands()
    {
        var vm = new RestoreBackupViewModel(new FakeBackupService([]), "TestServer", NoOpUiService.Instance, "/backups", static () => false);
        await vm.RefreshBackupsAsync();

        Assert.Null(vm.SelectedBackup);
        Assert.False(vm.RestoreCommand.CanExecute(null));
        Assert.False(vm.DeleteCommand.CanExecute(null));
    }

    [Fact]
    public async Task RestoreAsync_SelectionChangedDuringConfirm_UsesSnapshot()
    {
        var backupService = new FakeBackupService([
            new ServerBackupInfo("first.zip", "/backups/first.zip", 1, DateTimeOffset.UtcNow),
            new ServerBackupInfo("second.zip", "/backups/second.zip", 1, DateTimeOffset.UtcNow)
        ]);
        RestoreBackupViewModel? vm = null;
        var ui = new ManualUiService { OnConfirm = () => vm!.SelectedBackup = vm.Backups[1] };
        vm = new RestoreBackupViewModel(backupService, "TestServer", ui, "/backups", static () => false);
        await vm.RefreshBackupsAsync();

        await vm.RestoreAsync();

        Assert.Equal("first.zip", backupService.RestoredFileName);
        Assert.False(vm.IsOperating);
    }

    private sealed class FakeBackupService(IReadOnlyList<ServerBackupInfo> backups) : IServerBackupService
    {
        public bool RestoreCalled { get; private set; }

        public string? RestoredFileName { get; private set; }

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
            RestoredFileName = backupFileName;
            return Task.FromResult(true);
        }

        public Task<bool> DeleteBackupAsync(
            string serverName,
            string backupFileName,
            string? backupDirectory = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(true);

        public Task<ServerBackupSummary> GetBackupSummaryAsync(string serverName, string? backupDirectory, CancellationToken cancellationToken = default) =>
            Task.FromResult(new ServerBackupSummary(ServerBackupSummaryStatus.HasBackups, backups.Count));

        public Task<string?> ValidateBackupDestinationAsync(string destinationPath, CancellationToken cancellationToken = default) =>
            Task.FromResult<string?>(null);

        public Task<string> PrepareBackupFilePathAsync(string serverName, string destinationDirectory, CancellationToken cancellationToken = default) =>
            Task.FromResult(Path.Combine(destinationDirectory, $"backup-{serverName}.zip"));
    }
}
