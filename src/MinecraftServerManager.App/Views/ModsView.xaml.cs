using System.Diagnostics.CodeAnalysis;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>模組管理與線上探索分頁 View</summary>
public sealed partial class ModsView : UserControl
{
    public ModsViewModel ViewModel { get; }

    public ModsView(ModsViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
    }

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance method")]
    public Visibility GetLocalTabVisibility(int index) => index == 0 ? Visibility.Visible : Visibility.Collapsed;

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance method")]
    public Visibility GetOnlineTabVisibility(int index) => index == 1 ? Visibility.Visible : Visibility.Collapsed;

    private void OnLocalModsSelectionChanged(object sender, SelectionChangedEventArgs e) =>
        ViewModel.Local.SetSelectedMods(LocalModsListView.SelectedItems.OfType<LocalModRowItem>());

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

    public ITableSortTarget LocalSort => field ??= new TableSortTarget<LocalModRowItem>(() => ViewModel.Local.LocalMods, TableSortKeys.LocalMods);

    public ITableSortTarget OnlineSort => field ??= new TableSortTarget<OnlineModRowItem>(() => ViewModel.Online.OnlineMods, TableSortKeys.OnlineMods);

    private void OnOnlineModsDoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e) => ViewModel.PickOnlineModVersionCommand.TryExecute();

    private void OnlineSearchBox_KeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter && ViewModel.Online.SearchOnlineModsCommand.TryExecute())
        {
            e.Handled = true;
        }
    }

    private void OnModToggleClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: LocalModRowItem item })
        {
            ViewModel.Local.ToggleModCommand.TryExecute(item);
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
