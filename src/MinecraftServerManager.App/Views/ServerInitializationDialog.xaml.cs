using System.Diagnostics.CodeAnalysis;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器初次啟動初始化視窗（原生模態視窗，透過 ModalWindowHost 裝載）；流程與狀態由 <see cref="ServerInitializationViewModel"/> 管理</summary>
public sealed partial class ServerInitializationDialog : Window, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInitializationDialog));

    public ServerInitializationViewModel ViewModel { get; }

    public bool IsSuccess => ViewModel.IsSuccess;

    public ServerInitializationDialog(ServerInitializationViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "伺服器初次啟動初始化", 780, 540, Bindings.StopTracking);
        ViewModel.CloseRequested += Close;

        if (Content is FrameworkElement fe)
        {
            fe.Loaded += ServerInitializationDialog_Loaded;
        }

        AppWindow.Closing += ServerInitializationDialog_Closing;
    }

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance method")]
    public string CountdownBrushKey(InitializationCountdownState state) =>
        state == InitializationCountdownState.Success ? UiBindHelpers.SuccessTextBrushKey : UiBindHelpers.WarningTextBrushKey;

    private async void ServerInitializationDialog_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            await ViewModel.StartAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "初始化視窗啟動流程失敗");
        }
    }

    private void ConsoleBox_TextChanged(object sender, TextChangedEventArgs e) => ConsoleBox.SelectionStart = ConsoleBox.Text.Length;

    private void CancelButton_Click(object sender, RoutedEventArgs e) => ViewModel.Cancel();

    private void CompleteButton_Click(object sender, RoutedEventArgs e) => ViewModel.Complete();

    private void ServerInitializationDialog_Closing(Microsoft.UI.Windowing.AppWindow sender, Microsoft.UI.Windowing.AppWindowClosingEventArgs args)
    {
        try
        {
            args.Cancel = ViewModel.HandleClosing();
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "ServerInitializationDialog_Closing 失敗");
        }
    }

    /// <summary>解除與 ViewModel 的事件連結（ViewModel 由建立者負責釋放）</summary>
    public void Dispose() => ViewModel.CloseRequested -= Close;
}
