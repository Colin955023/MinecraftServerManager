using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器記憶體設定 WinUI 3 原生 ContentDialog
/// </summary>
public sealed partial class ServerMemoryDialog : ContentDialog
{
    public ServerMemoryViewModel ViewModel { get; }

    public ServerMemoryDialog(ServerMemoryViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        InitializeComponent();

        ViewModel = viewModel;
        viewModel.RequestClose += success =>
        {
            if (success)
            {
                Hide();
            }
        };
    }

    private void Dialog_PrimaryButtonClick(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        if (ViewModel.SaveCommand.CanExecute(null))
        {
            ViewModel.SaveCommand.Execute(null);
        }
    }
}
