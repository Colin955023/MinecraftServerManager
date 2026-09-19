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
}
