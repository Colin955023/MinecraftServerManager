using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 建立新伺服器分頁 View
/// </summary>
public sealed partial class CreateServerView : UserControl
{
    public CreateServerViewModel ViewModel { get; }

    public CreateServerView(CreateServerViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
    }
}
