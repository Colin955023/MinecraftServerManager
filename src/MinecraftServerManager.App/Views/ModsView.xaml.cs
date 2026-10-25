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
            foreach (var item in e.RemovedItems.OfType<LocalModRowItem>())
            {
                item.IsSelected = false;
            }
            foreach (var item in e.AddedItems.OfType<LocalModRowItem>())
            {
                item.IsSelected = true;
            }
            vm.UpdateSelectionState(grid.SelectedItems.Count);
        }
    }

    private void OnlineModsGrid_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (DataContext is ModsViewModel vm && sender is DataGrid grid && grid.SelectedItem is OnlineModRowItem item)
        {
            _ = ViewModelBase.RunSafeAsync(() => vm.PickOnlineModVersionAsync(item), "選取線上模組版本");
        }
    }

    private void OnViewPreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.OriginalSource is System.Windows.DependencyObject dep)
        {
            if (FindVisualParent<Button>(dep) != null ||
                FindVisualParent<DataGridRow>(dep) != null ||
                FindVisualParent<System.Windows.Controls.Primitives.ScrollBar>(dep) != null ||
                FindVisualParent<System.Windows.Controls.Primitives.Thumb>(dep) != null ||
                FindVisualParent<TextBox>(dep) != null ||
                FindVisualParent<ComboBox>(dep) != null ||
                FindVisualParent<TabItem>(dep) != null)
            {
                return;
            }
        }

        if (DataContext is ModsViewModel vm)
        {
            vm.SelectedLocalMod = null;
            vm.SelectedOnlineMod = null;
            LocalModsGrid.SelectedItems.Clear();
            foreach (var item in vm.LocalMods)
            {
                item.IsSelected = false;
            }
            vm.UpdateSelectionState(0);
        }
    }

    private static T? FindVisualParent<T>(System.Windows.DependencyObject? child) where T : System.Windows.DependencyObject
    {
        while (child != null)
        {
            if (child is T parent)
            {
                return parent;
            }

            child = System.Windows.Media.VisualTreeHelper.GetParent(child);
        }
        return null;
    }
}

