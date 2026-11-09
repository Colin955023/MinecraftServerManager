using System.Diagnostics.CodeAnalysis;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 模組管理與線上探索分頁 View
/// </summary>
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

    private void OnLocalSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Local.LocalMods.SortBy(TableSortKeys.LocalMods, e);

    private void OnLocalAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Local.LocalMods, TableSortKeys.LocalMods);

    private void OnOnlineSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Online.OnlineMods.SortBy(TableSortKeys.OnlineMods, e);

    private void OnOnlineAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Online.OnlineMods, TableSortKeys.OnlineMods);

    private void OnOnlineModsDoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e)
    {
        if (ViewModel.PickOnlineModVersionCommand.CanExecute(null))
        {
            ViewModel.PickOnlineModVersionCommand.Execute(null);
        }
    }

    private void OnlineSearchBox_KeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter && ViewModel.Online.SearchOnlineModsCommand.CanExecute(null))
        {
            ViewModel.Online.SearchOnlineModsCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void OnCopyLocalModInfoClicked(object sender, RoutedEventArgs e)
    {
        if (ViewModel.Local.SelectedLocalMod is not null && ViewModel.Local.CopyModInfoCommand.CanExecute(ViewModel.Local.SelectedLocalMod))
        {
            ViewModel.Local.CopyModInfoCommand.Execute(ViewModel.Local.SelectedLocalMod);
        }
    }

    private void OnShowInFolderClicked(object sender, RoutedEventArgs e)
    {
        if (ViewModel.Local.SelectedLocalMod is not null && ViewModel.Local.ShowInFolderCommand.CanExecute(ViewModel.Local.SelectedLocalMod))
        {
            ViewModel.Local.ShowInFolderCommand.Execute(ViewModel.Local.SelectedLocalMod);
        }
    }

    private void OnModToggleClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: LocalModRowItem item } && ViewModel.Local.ToggleModCommand.CanExecute(item))
        {
            ViewModel.Local.ToggleModCommand.Execute(item);
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
