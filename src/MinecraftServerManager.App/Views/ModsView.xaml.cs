using System.Windows.Controls;
using System.Windows.Input;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ModsView : UserControl
{
    public ModsView()
    {
        InitializeComponent();
    }

    private void LocalModsGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (DataContext is ModsViewModel vm && sender is DataGrid grid)
        {
            var selectedSet = grid.SelectedItems.OfType<LocalModRowItem>().ToHashSet();
            foreach (var item in vm.LocalMods)
            {
                item.IsSelected = selectedSet.Contains(item);
            }
            vm.UpdateSelectionState(grid.SelectedItems.Count);
        }
    }

    private void LocalModsGrid_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (DataContext is ModsViewModel vm && sender is DataGrid grid && grid.SelectedItem is LocalModRowItem item)
        {
            _ = vm.ToggleModAsync(item);
        }
    }
}

