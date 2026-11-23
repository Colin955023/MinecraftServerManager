using System.Collections.ObjectModel;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModDialogViewModelTests
{
    [Fact]
    public void UpdateSelection_NoSelection_DisablesConfirm()
    {
        ModUpdateCandidateItem first = new() { ModName = "A" };
        ModUpdateCandidateItem second = new() { ModName = "B" };
        using var vm = new ModUpdateSelectionViewModel([first, second]);
        bool? closed = null;
        vm.RequestClose += result => closed = result;

        vm.DeselectAll();
        Assert.False(vm.ConfirmCommand.CanExecute(null));

        second.IsSelected = true;
        Assert.True(vm.ConfirmCommand.CanExecute(null));
        vm.ConfirmCommand.Execute(null);

        Assert.True(closed);
        Assert.Equal([second], vm.GetSelectedItems());
    }

    [Fact]
    public void InstallQueueReview_QueueCountChanged_UpdatesCommands()
    {
        ObservableCollection<ModInstallQueueItem> queue = [new() { Title = "A" }];
        using var vm = new ModInstallQueueReviewViewModel(queue);
        bool? closed = null;
        vm.RequestClose += result => closed = result;

        Assert.True(vm.StartInstallCommand.CanExecute(null));
        vm.ClearQueueCommand.Execute(null);

        Assert.Empty(queue);
        Assert.False(vm.StartInstallCommand.CanExecute(null));
        Assert.False(vm.ClearQueueCommand.CanExecute(null));

        vm.CloseCommand.Execute(null);
        Assert.False(closed);
    }
}
