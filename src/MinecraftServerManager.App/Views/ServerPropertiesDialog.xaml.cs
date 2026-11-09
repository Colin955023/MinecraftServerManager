using Microsoft.UI.Xaml;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器屬性設定視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class ServerPropertiesDialog : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesDialog));

    public ServerPropertiesViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ServerPropertiesDialog(ServerPropertiesViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        Title = "編輯伺服器屬性";

        WindowLayoutHelper.ResizeToDip(this, 760, 680);

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            // 延後至 async 命令完成後再關閉，避免命令結束時更新已關閉視窗的按鈕狀態造成原生閃退
            DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, CloseAfterSave);
        };

        AppWindow.Closing += async (sender, args) =>
        {
            try
            {
                if (DialogResult is null && ViewModel.HasUnsavedChanges)
                {
                    args.Cancel = true;
                    if (await ViewModel.ConfirmDiscardAsync().ConfigureAwait(true))
                    {
                        DialogResult = false;
                        Close();
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "伺服器屬性設定視窗關閉確認異常: {Message}", ex.Message);
            }
        };
    }

    /// <summary>
    /// 先停止 x:Bind 追蹤並解除清單資料來源，再關閉視窗，避免拆除視覺樹時繫結回寫已釋放的控制項
    /// </summary>
    private void CloseAfterSave()
    {
        try
        {
            Bindings.StopTracking();
            PropertiesListView.ItemsSource = null;
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "關閉伺服器屬性視窗前解除繫結失敗: {Message}", ex.Message);
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
