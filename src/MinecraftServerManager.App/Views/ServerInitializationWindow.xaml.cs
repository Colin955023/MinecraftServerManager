using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器初次啟動初始化視窗</summary>
public sealed partial class ServerInitializationWindow : Window, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInitializationWindow));

    private readonly LogListAutoScroller _autoScroller;
    private readonly Microsoft.UI.Windowing.AppWindow _appWindow;

    public ServerInitializationWindow(ServerInitializationViewModel viewModel, IUiService ui)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ArgumentNullException.ThrowIfNull(ui);
        ViewModel = viewModel;
        InitializeComponent();
        _autoScroller = new LogListAutoScroller(ConsoleListView, viewModel.ConsoleLines, ui);
        // 初始化期間不可由 Escape 中斷
        ModalWindowHost.ConfigureDialogWindow(this, viewModel.TitleText, 780, 540, Bindings.StopTracking, closeOnEscape: false);
        ModalWindowHost.BindRequestClose(this, ViewModel);
        ModalWindowHost.RunOnLoadedOnce(this, ViewModel.StartAsync, Logger, "初始化視窗啟動流程");

        _appWindow = AppWindow;
        _appWindow.Closing += OnWindowClosing;
        Closed += (_, _) => Dispose();
    }

    private bool _disposed;

    public ServerInitializationViewModel ViewModel { get; }

    public bool IsSuccess => ViewModel.IsSuccess;

    public static string CountdownBrushKey(InitializationCountdownState state) =>
        state == InitializationCountdownState.Success ? UiBindHelpers.SuccessTextBrushKey : UiBindHelpers.WarningTextBrushKey;

    /// <summary>解除與事件及自動捲動之連結（ViewModel 由建立者負責釋放）</summary>
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _appWindow.Closing -= OnWindowClosing;
        _autoScroller.Dispose();
    }

    private void OnWindowClosing(Microsoft.UI.Windowing.AppWindow sender, Microsoft.UI.Windowing.AppWindowClosingEventArgs args)
    {
        try
        {
            args.Cancel = ViewModel.HandleClosing();
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "OnWindowClosing 失敗");
        }
    }
}
