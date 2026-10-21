using System.ComponentModel;
using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器名單管理對話方塊 Code-Behind
/// </summary>
public partial class PlayerManagementDialog : Window
{
    private readonly PlayerManagementViewModel _viewModel;

    public PlayerManagementDialog(PlayerManagementViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;

        Loaded += async (_, _) => await _viewModel.InitializeAsync().ConfigureAwait(true);

        _viewModel.RequestClose += success =>
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
