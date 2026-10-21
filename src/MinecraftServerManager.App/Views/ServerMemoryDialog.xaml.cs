using System.ComponentModel;
using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器記憶體設定對話方塊 Code-Behind
/// </summary>
public partial class ServerMemoryDialog : Window
{
    private readonly ServerMemoryViewModel _viewModel;

    public ServerMemoryDialog(ServerMemoryViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
        viewModel.RequestClose += success =>
        {
            DialogResult = success;
            Close();
        };

        Closing += OnWindowClosing;
    }

    private void OnWindowClosing(object? sender, CancelEventArgs e)
    {
        if (DialogResult is null && _viewModel.HasUnsavedChanges)
        {
            if (!_viewModel.ConfirmDiscard())
            {
                e.Cancel = true;
            }
        }
    }
}
