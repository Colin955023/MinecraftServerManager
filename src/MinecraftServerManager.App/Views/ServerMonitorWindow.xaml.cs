using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器監控與主控台即時視窗</summary>
public sealed partial class ServerMonitorWindow : Window, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMonitorWindow));

    private readonly ServerMonitorViewModel _viewModel;
    private readonly LogListAutoScroller _autoScroller;

    public ServerMonitorWindow(ServerMonitorViewModel viewModel, IUiService ui, ElementTheme theme)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ArgumentNullException.ThrowIfNull(ui);
        _viewModel = viewModel;

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

        RootGrid.RequestedTheme = theme;
        WindowChromeService.ApplyTheme(AppWindow, theme);

        _autoScroller = new LogListAutoScroller(LogListView, _viewModel.Logs, ui, () => _viewModel.IsAutoScrollEnabled);

        Closed += OnServerMonitorWindowClosed;
    }

    public ServerMonitorViewModel ViewModel => _viewModel;

    /// <summary>解除日誌自動捲動訂閱</summary>
    public void Dispose() => _autoScroller.Dispose();

    /// <summary>方向鍵瀏覽歷史指令（TextBox 會自行處理方向鍵，故用 PreviewKeyDown）</summary>
    private void OnCommandInputBoxPreviewKeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
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
            _viewModel.CopyPlayerNameCommand.Execute(playerName);
        }
    }

    private void OnServerMonitorWindowClosed(object sender, WindowEventArgs args)
    {
        Dispose();
        Bindings.StopTracking();
        Logger.Information("伺服器監控視窗已關閉");
    }
}
