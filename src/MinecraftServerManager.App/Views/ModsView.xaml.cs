using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>模組管理與線上探索分頁 View</summary>
public sealed partial class ModsView : UserControl
{
    public ModsView(ModsViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        DeleteModsAccelerator.ScopeOwner = LocalModsListView;
    }

    public ModsViewModel ViewModel { get; }

    public ITableSortTarget LocalSort => field ??= new TableSortTarget<LocalModRowItem>(() => ViewModel.Local.LocalMods, TableSortKeys.LocalMods);

    public ITableSortTarget OnlineSort => field ??= new TableSortTarget<OnlineModRowItem>(() => ViewModel.Online.OnlineMods, TableSortKeys.OnlineMods);

    public static Visibility GetLocalTabVisibility(int index) => index == 0 ? Visibility.Visible : Visibility.Collapsed;

    public static Visibility GetOnlineTabVisibility(int index) => index == 1 ? Visibility.Visible : Visibility.Collapsed;

    private void OnLocalModsSelectionChanged(object sender, SelectionChangedEventArgs e) =>
        ViewModel.Local.SetSelectedMods(LocalModsListView.SelectedItems.OfType<LocalModRowItem>());

    private void OnLocalModToggleClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: LocalModRowItem mod })
        {
            ViewModel.Local.ToggleModCommand.Execute(mod);
        }
    }

    private void OnSelectAllLocalModsClicked(object sender, RoutedEventArgs e)
    {
        if (LocalModsListView.SelectedItems.Count == ViewModel.Local.LocalMods.Count && LocalModsListView.SelectedItems.Count > 0)
        {
            LocalModsListView.SelectedItems.Clear();
        }
        else
        {
            LocalModsListView.SelectAll();
        }
    }

    private void OnTabSelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        int index = sender.Items.IndexOf(sender.SelectedItem);
        if (index >= 0)
        {
            ViewModel.SelectedTabIndex = index;
        }
    }
}
