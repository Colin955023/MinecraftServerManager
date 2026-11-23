using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器記憶體設定對話方塊</summary>
public sealed partial class ServerMemoryDialog : ContentDialog
{
    public ServerMemoryDialog(ServerMemoryViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
    }

    public ServerMemoryViewModel ViewModel { get; }

    /// <summary>儲存完成才關閉；失敗時保留對話框並顯示資訊列</summary>
    private async void OnPrimaryButtonClicked(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        ContentDialogButtonClickDeferral deferral = args.GetDeferral();
        try
        {
            args.Cancel = !await ViewModel.SaveAsync();
        }
        finally
        {
            deferral.Complete();
        }
    }
}
