using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageServerViewModelTests
{
    [Fact]
    public void SelectionShouldUpdateActionState()
    {
        var vm = new ManageServerViewModel();
        Assert.False(vm.HasSelectedServer);
        Assert.False(vm.StartServerCommand.CanExecute(null));
        Assert.False(vm.StopServerCommand.CanExecute(null));
        Assert.False(vm.MonitorServerCommand.CanExecute(null));
        Assert.False(vm.ConfigureServerCommand.CanExecute(null));
        Assert.False(vm.OpenServerFolderCommand.CanExecute(null));
        Assert.False(vm.BackupServerCommand.CanExecute(null));
        Assert.False(vm.RestoreBackupCommand.CanExecute(null));
        Assert.False(vm.DeleteServerCommand.CanExecute(null));

        var server = new ServerRowItem
        {
            Name = "Survival",
            Version = "1.21.4",
            Loader = "Vanilla",
            Status = "已停止",
            Path = @"C:\servers\Survival"
        };
        vm.SelectedServer = server;

        Assert.True(vm.HasSelectedServer);
        Assert.Contains("Survival", vm.SelectedServerInfo);
        Assert.True(vm.StartServerCommand.CanExecute(null));
        Assert.True(vm.StopServerCommand.CanExecute(null));
        Assert.True(vm.MonitorServerCommand.CanExecute(null));
        Assert.True(vm.ConfigureServerCommand.CanExecute(null));
        Assert.True(vm.OpenServerFolderCommand.CanExecute(null));
        Assert.True(vm.BackupServerCommand.CanExecute(null));
        Assert.True(vm.RestoreBackupCommand.CanExecute(null));
        Assert.True(vm.DeleteServerCommand.CanExecute(null));

        vm.SelectedServer = null;
        Assert.False(vm.HasSelectedServer);
        Assert.False(vm.StartServerCommand.CanExecute(null));
        Assert.False(vm.DeleteServerCommand.CanExecute(null));
    }

    [Fact]
    public async Task OpenBackupFolderWithoutBackupPathShouldNotCreateOrOpenServerInternalBackups()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "msm-backup-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        try
        {
            var fakeLauncher = new FakeExternalLauncher();
            var vm = new ManageServerViewModel(launcher: fakeLauncher)
            {
                SelectedServer = new ServerRowItem
                {
                    Name = "TestServer",
                    Version = "1.21.4",
                    Loader = "Paper",
                    Status = "已停止",
                    Path = tempDir,
                    BackupPath = string.Empty
                }
            };

            // 執行 OpenBackupFolder，未設定 BackupPath 且 DialogHelper 在測試中預設不會確認開啟
            await vm.OpenBackupFolderCommand.ExecuteAsync(null);

            string internalBackupDir = Path.Combine(tempDir, "backups");
            Assert.False(Directory.Exists(internalBackupDir));
            Assert.DoesNotContain(internalBackupDir, fakeLauncher.OpenedFolders);
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch { }
        }
    }

    private sealed class FakeExternalLauncher : Core.Ports.IExternalLauncher
    {
        public List<string> OpenedFolders { get; } = [];
        public bool OpenFolder(string folderPath)
        {
            OpenedFolders.Add(folderPath);
            return true;
        }
        public bool ShowInFolder(string filePath) => !string.IsNullOrEmpty(filePath);
        public bool OpenUrl(string url) => !string.IsNullOrEmpty(url);
    }
}
