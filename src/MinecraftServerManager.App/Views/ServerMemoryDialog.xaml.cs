using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器記憶體設定對話框 Code-Behind
/// </summary>
public partial class ServerMemoryDialog : Window
{
    public ServerMemoryDialog(ServerMemoryViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        viewModel.RequestClose += success =>
        {
            DialogResult = success;
            Close();
        };
    }
}
