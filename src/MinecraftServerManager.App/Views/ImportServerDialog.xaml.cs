using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>匯入伺服器對話方塊</summary>
public sealed partial class ImportServerDialog : ContentDialog
{
    public ImportServerDialog(ImportServerViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
    }

    public ImportServerViewModel ViewModel { get; }

    private void OnPrimaryButtonClicked(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        if (!ViewModel.ValidateInputs())
        {
            args.Cancel = true;
        }
    }
}
