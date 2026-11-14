using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器屬性設定視窗</summary>
public sealed partial class ServerPropertiesDialog : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesDialog));

    public ServerPropertiesViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ServerPropertiesDialog(ServerPropertiesViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "編輯伺服器屬性", 760, 680, Bindings.StopTracking);

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            // 延後關閉，避免命令結束時更新已關閉視窗而閃退
            DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, CloseAfterSave);
        };

        ModalWindowHost.RegisterUnsavedChangesPrompt(
            this,
            () => DialogResult is null && ViewModel.HasUnsavedChanges,
            ViewModel.ConfirmDiscardAsync,
            () => DialogResult = false,
            Logger);
    }

    /// <summary>先解除繫結與清單資料來源再關閉視窗</summary>
    private void CloseAfterSave()
    {
        try
        {
            Bindings.StopTracking();
            PropertiesListView.ItemsSource = null;
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "關閉伺服器屬性視窗前解除繫結失敗");
        }

        Close();
    }

    private void ResetItem_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: PropertyEditItem item })
        {
            item.ResetToDefault();
        }
    }
}
