using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>JVM 啟動參數設定對話方塊</summary>
public sealed partial class JvmArgsDialog : ContentDialog
{
    public JvmArgsViewModel ViewModel { get; }

    public JvmArgsDialog(JvmArgsViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
    }
}
