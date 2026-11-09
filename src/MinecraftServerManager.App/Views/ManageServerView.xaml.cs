using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 管理伺服器頁面 View
/// </summary>
public sealed partial class ManageServerView : UserControl
{
    public static readonly DependencyProperty ViewModelProperty =
        DependencyProperty.Register(
            nameof(ViewModel),
            typeof(ManageServerViewModel),
            typeof(ManageServerView),
            new PropertyMetadata(null, OnViewModelChanged));

    public ManageServerViewModel? ViewModel
    {
        get => (ManageServerViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public ManageServerView()
    {
        InitializeComponent();
        DataContextChanged += ManageServerView_DataContextChanged;
    }

    private void ManageServerView_DataContextChanged(FrameworkElement sender, DataContextChangedEventArgs args)
    {
        if (args.NewValue is ManageServerViewModel vm)
        {
            ViewModel = vm;
        }
    }

    private static void OnViewModelChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is ManageServerView view)
        {
            view.Bindings.Update();
        }
    }

    private void OnServersListViewDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        if (ViewModel is not null && ViewModel.MonitorServerCommand.CanExecute(null))
        {
            ViewModel.MonitorServerCommand.Execute(null);
        }
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel is null || ViewModel.Servers.Count <= 1)
        {
            return;
        }

        ViewModel.Servers.SortBy(e);
    }

    private void OnHeaderAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel is null || ViewModel.Servers.Count == 0)
        {
            return;
        }

        var columns = ServerListColumns.Current;
        switch (propertyName)
        {
            case "Name":
                ToggleColumnWidth(
                    () => columns.NameWidth.Value,
                    w => columns.NameWidth = new(w),
                    ServerListColumns.DefaultNameWidth,
                    ViewModel.Servers.Select(s => s.Name),
                    "名稱");
                break;
            case "Version":
                ToggleColumnWidth(
                    () => columns.VersionWidth.Value,
                    w => columns.VersionWidth = new(w),
                    ServerListColumns.DefaultVersionWidth,
                    ViewModel.Servers.Select(s => s.Version),
                    "版本");
                break;
            case "Loader":
                ToggleColumnWidth(
                    () => columns.LoaderWidth.Value,
                    w => columns.LoaderWidth = new(w),
                    ServerListColumns.DefaultLoaderWidth,
                    ViewModel.Servers.Select(s => s.Loader),
                    "載入器");
                break;
            case "Status":
                ToggleColumnWidth(
                    () => columns.StatusWidth.Value,
                    w => columns.StatusWidth = new(w),
                    ServerListColumns.DefaultStatusWidth,
                    ViewModel.Servers.Select(s => s.Status),
                    "狀態");
                break;
            case "Size":
                ToggleColumnWidth(
                    () => columns.SizeWidth.Value,
                    w => columns.SizeWidth = new(w),
                    ServerListColumns.DefaultSizeWidth,
                    ViewModel.Servers.Select(s => s.Size),
                    "目錄大小");
                break;
            case "LastModified":
                ToggleColumnWidth(
                    () => columns.ModifiedWidth.Value,
                    w => columns.ModifiedWidth = new(w),
                    ServerListColumns.DefaultModifiedWidth,
                    ViewModel.Servers.Select(s => s.LastModified),
                    "修改日期");
                break;
            case "BackupStatus":
                ToggleColumnWidth(
                    () => columns.BackupWidth.Value,
                    w => columns.BackupWidth = new(w),
                    ServerListColumns.DefaultBackupWidth,
                    ViewModel.Servers.Select(s => s.BackupStatus),
                    "備份狀態");
                break;
            case "RelativePath":
                ToggleColumnWidth(
                    () => columns.PathWidth.Value,
                    w => columns.PathWidth = new(w),
                    ServerListColumns.DefaultPathWidth,
                    ViewModel.Servers.Select(s => s.RelativePath),
                    "相對路徑");
                break;
        }
    }

    /// <summary>
    /// 點兩下自動調整欄寬對齊該欄最寬項目（包含表頭與所有列內容）。
    /// </summary>
    internal static void ToggleColumnWidth(
        Func<double> getCurrentWidth,
        Action<double> setWidth,
        double defaultWidth,
        IEnumerable<string?> values,
        string? headerText = null)
    {
        ArgumentNullException.ThrowIfNull(getCurrentWidth);
        ArgumentNullException.ThrowIfNull(setWidth);
        ArgumentNullException.ThrowIfNull(values);

        double autoFit = SortableTableHeader.CalculateAutoFitWidth(defaultWidth, values, headerText);
        setWidth(autoFit);
    }
}
