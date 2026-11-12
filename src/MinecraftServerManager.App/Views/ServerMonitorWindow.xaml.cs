using System.Collections.Specialized;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
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

        ExtendsContentIntoTitleBar = true;

        WindowIconHelper.SetIcon(AppWindow);
        Title = _viewModel.WindowTitle;

        WindowLayoutHelper.ResizeToDip(this, 1050, 680);
        SetTitleBar(AppTitleBar);

        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.IsMinimizable = true;
            presenter.IsMaximizable = true;
            presenter.IsResizable = true;
        }

        if (_ui is WinUiService winUi)
        {
            RootGrid.RequestedTheme = winUi.CurrentTheme;
            TitleBarThemeHelper.ApplyTitleBarTheme(AppWindow, winUi.CurrentTheme);
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
                    // 主控台常有重複內容（空行、相同提示），ScrollIntoView(字串) 會以第一個相同字串定位，
                    // 導致清單先跳回上方再跳回底部而看似整個重刷；改為直接捲動內部 ScrollViewer 至底部
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

    private async void CommandInputBox_KeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
        {
            // 須在 await 前標記，事件路由於第一個 await 後即已完成
            e.Handled = true;
            try
            {
                await _viewModel.SendCommandAsync().ConfigureAwait(true);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "傳送主控台指令時發生例外");
            }
        }
    }

    /// <summary>方向鍵上下瀏覽歷史指令；用 PreviewKeyDown 是因為 TextBox 會自行處理方向鍵而不引發 KeyDown</summary>
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
        _viewModel.Dispose();
        Logger.Information("伺服器監控視窗已關閉");
    }
}
