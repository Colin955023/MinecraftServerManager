using System.Collections.Specialized;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器監控與主控台即時視窗</summary>
public sealed partial class ServerMonitorWindow : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMonitorWindow));

    private readonly ServerMonitorViewModel _viewModel;
    private readonly IUiService _ui;
    private bool _scrollQueued;
    private ScrollViewer? _logScrollViewer;

    public ServerMonitorViewModel ViewModel => _viewModel;

    public ServerMonitorWindow(ServerMonitorViewModel viewModel, IUiService ui)
    {
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        _ui = ui ?? throw new ArgumentNullException(nameof(ui));

        InitializeComponent();

        WindowIconHelper.SetIcon(AppWindow);
        Title = _viewModel.WindowTitle;

        WindowLayoutHelper.ResizeToDip(this, 1050, 680);
        WindowLayoutHelper.SetMinimumSizeDip(this, 720, 480);
        WindowChromeService.Apply(this, AppTitleBar);

        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.IsMinimizable = true;
            presenter.IsMaximizable = true;
            presenter.IsResizable = true;
        }

        if (_ui is WinUiService winUi)
        {
            RootGrid.RequestedTheme = winUi.CurrentTheme;
            WindowChromeService.ApplyTheme(AppWindow, winUi.CurrentTheme);
        }

        if (_viewModel.Logs is INotifyCollectionChanged notify)
        {
            notify.CollectionChanged += OnLogsCollectionChanged;
        }

        Closed += ServerMonitorWindow_Closed;
    }

    private void OnLogsCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (_viewModel.IsAutoScrollEnabled &&
            e.Action is NotifyCollectionChangedAction.Add or NotifyCollectionChangedAction.Reset &&
            _viewModel.Logs.Count > 0 &&
            !_scrollQueued)
        {
            _scrollQueued = true;
            _ui.PostToUi(() =>
            {
                _scrollQueued = false;
                if (!_viewModel.IsAutoScrollEnabled || _viewModel.Logs.Count == 0)
                {
                    return;
                }

                try
                {
                    // ScrollIntoView(字串) 會定位到第一個相同字串而造成跳動，改為直接捲動內部 ScrollViewer
                    _logScrollViewer ??= FindDescendant<ScrollViewer>(LogListView);
                    if (_logScrollViewer is not null)
                    {
                        _logScrollViewer.ChangeView(null, _logScrollViewer.ScrollableHeight, null, disableAnimation: true);
                    }
                    else
                    {
                        LogListView.ScrollIntoView(_viewModel.Logs[^1]);
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning(ex, "日誌自動捲動失敗");
                }
            }, afterLayout: true);
        }
    }

    private static T? FindDescendant<T>(DependencyObject root) where T : DependencyObject
    {
        int count = VisualTreeHelper.GetChildrenCount(root);
        for (int i = 0; i < count; i++)
        {
            DependencyObject child = VisualTreeHelper.GetChild(root, i);
            if (child is T match)
            {
                return match;
            }

            if (FindDescendant<T>(child) is { } nested)
            {
                return nested;
            }
        }

        return null;
    }

    private void CommandInputBox_KeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
        {
            e.Handled = true;
            _viewModel.SendCommandCommand.TryExecute();
        }
    }

    /// <summary>方向鍵瀏覽歷史指令（TextBox 會自行處理方向鍵，故用 PreviewKeyDown）</summary>
    private void CommandInputBox_PreviewKeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key is not (Windows.System.VirtualKey.Up or Windows.System.VirtualKey.Down) || sender is not TextBox box)
        {
            return;
        }

        if (_viewModel.NavigateHistory(previous: e.Key == Windows.System.VirtualKey.Up) is { } text)
        {
            box.Text = text;
            box.SelectionStart = text.Length;
            e.Handled = true;
        }
    }

    private void OnPlayerItemClicked(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is string playerName)
        {
            _viewModel.CopyPlayerName(playerName);
        }
    }

    private void OnCopyAllLogsClicked(object sender, RoutedEventArgs e) => _viewModel.CopyAllLogs();

    private void ServerMonitorWindow_Closed(object sender, WindowEventArgs args)
    {
        if (_viewModel.Logs is INotifyCollectionChanged notify)
        {
            notify.CollectionChanged -= OnLogsCollectionChanged;
        }
        Bindings.StopTracking();
        Logger.Information("伺服器監控視窗已關閉");
    }
}
