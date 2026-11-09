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
    public static readonly DependencyProperty ViewModelProperty =
        DependencyProperty.Register(
            nameof(ViewModel),
            typeof(ModsViewModel),
            typeof(ModsView),
            new PropertyMetadata(null, OnViewModelChanged));

    public ModsViewModel? ViewModel
    {
        get => (ModsViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public ModsView()
    {
        InitializeComponent();
        DataContextChanged += ModsView_DataContextChanged;
    }

    private void ModsView_DataContextChanged(FrameworkElement sender, DataContextChangedEventArgs args)
    {
        if (args.NewValue is ModsViewModel vm)
        {
            ViewModel = vm;
        }
    }

    private static void OnViewModelChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is ModsView view)
        {
            view.Bindings.Update();
        }
    }

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance method")]
    public Visibility GetLocalTabVisibility(int index) => index == 0 ? Visibility.Visible : Visibility.Collapsed;

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance method")]
    public Visibility GetOnlineTabVisibility(int index) => index == 1 ? Visibility.Visible : Visibility.Collapsed;

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance method")]
    public Style? GetTabButtonStyle(int selectedIndex, int targetIndex)
    {
        return selectedIndex == targetIndex
            ? (Style?)Application.Current.Resources["PrimaryButtonStyle"]
            : null;
    }

    private void OnLocalSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel is null || ViewModel.LocalMods.Count <= 1)
        {
            return;
        }

        ViewModel.LocalMods.SortBy(e);
    }

    private void OnLocalAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel is null || ViewModel.LocalMods.Count == 0)
        {
            return;
        }

        var cols = LocalModListColumns.Current;
        switch (propertyName)
        {
            case "IsEnabled":
                cols.EnabledWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultEnabledWidth, [], "啟用"));
                break;
            case "Name":
                cols.NameWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultNameWidth, ViewModel.LocalMods.Select(m => m.Name), "模組名稱"));
                break;
            case "Version":
                cols.VersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultVersionWidth, ViewModel.LocalMods.Select(m => m.Version), "版本"));
                break;
            case "Author":
                cols.AuthorWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultAuthorWidth, ViewModel.LocalMods.Select(m => m.Author), "作者"));
                break;
            case "LoaderType":
                cols.LoaderWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultLoaderWidth, ViewModel.LocalMods.Select(m => m.LoaderType), "載入器"));
                break;
            case "SourcePlatform":
                cols.PlatformWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultPlatformWidth, ViewModel.LocalMods.Select(m => m.SourcePlatform), "來源平台"));
                break;
            case "FileSize":
                cols.SizeWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultSizeWidth, ViewModel.LocalMods.Select(m => m.FileSize), "檔案大小"));
                break;
            case "ModifiedTime":
                cols.ModifiedWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultModifiedWidth, ViewModel.LocalMods.Select(m => m.ModifiedTime), "修改時間"));
                break;
            case "Description":
                cols.DescriptionWidth = new(SortableTableHeader.CalculateAutoFitWidth(LocalModListColumns.DefaultDescriptionWidth, ViewModel.LocalMods.Select(m => m.Description), "描述"));
                break;
        }
    }

    private void OnOnlineSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel is null || ViewModel.OnlineMods.Count <= 1)
        {
            return;
        }

        ViewModel.OnlineMods.SortBy(e);
    }

    private void OnOnlineAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel is null || ViewModel.OnlineMods.Count == 0)
        {
            return;
        }

        var cols = OnlineModListColumns.Current;
        switch (propertyName)
        {
            case "Title":
                cols.TitleWidth = new(SortableTableHeader.CalculateAutoFitWidth(OnlineModListColumns.DefaultTitleWidth, ViewModel.OnlineMods.Select(m => m.Title), "模組名稱"));
                break;
            case "Author":
                cols.AuthorWidth = new(SortableTableHeader.CalculateAutoFitWidth(OnlineModListColumns.DefaultAuthorWidth, ViewModel.OnlineMods.Select(m => m.Author), "作者"));
                break;
            case "Downloads":
                cols.DownloadsWidth = new(SortableTableHeader.CalculateAutoFitWidth(OnlineModListColumns.DefaultDownloadsWidth, ViewModel.OnlineMods.Select(m => m.Downloads), "下載量"));
                break;
            case "LatestVersion":
                cols.VersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(OnlineModListColumns.DefaultVersionWidth, ViewModel.OnlineMods.Select(m => m.LatestVersion), "最新版本"));
                break;
            case "Description":
                cols.DescriptionWidth = new(SortableTableHeader.CalculateAutoFitWidth(OnlineModListColumns.DefaultDescriptionWidth, ViewModel.OnlineMods.Select(m => m.Description), "簡介"));
                break;
        }
    }

    private void OnOnlineModsDoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e)
    {
        if (ViewModel?.PickOnlineModVersionCommand.CanExecute(null) == true)
        {
            ViewModel.PickOnlineModVersionCommand.Execute(null);
        }
    }

    private void OnlineSearchBox_KeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter && ViewModel?.SearchOnlineModsCommand.CanExecute(null) == true)
        {
            ViewModel.SearchOnlineModsCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void OnCopyLocalModInfoClicked(object sender, RoutedEventArgs e)
    {
        if (ViewModel?.SelectedLocalMod is not null && ViewModel.CopyModInfoCommand.CanExecute(ViewModel.SelectedLocalMod))
        {
            ViewModel.CopyModInfoCommand.Execute(ViewModel.SelectedLocalMod);
        }
    }

    private void OnShowInFolderClicked(object sender, RoutedEventArgs e)
    {
        if (ViewModel?.SelectedLocalMod is not null && ViewModel.ShowInFolderCommand.CanExecute(ViewModel.SelectedLocalMod))
        {
            ViewModel.ShowInFolderCommand.Execute(ViewModel.SelectedLocalMod);
        }
    }

    private void OnModToggleClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: LocalModRowItem item } && ViewModel?.ToggleModCommand.CanExecute(item) == true)
        {
            ViewModel.ToggleModCommand.Execute(item);
        }
    }

    [SuppressMessage("Style", "IDE0031:Use null propagation", Justification = "Cannot use null propagation on property assignment")]
    private void OnTabLocalClicked(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            vm.SelectedTabIndex = 0;
        }
    }

    [SuppressMessage("Style", "IDE0031:Use null propagation", Justification = "Cannot use null propagation on property assignment")]
    private void OnTabOnlineClicked(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            vm.SelectedTabIndex = 1;
        }
    }
}
