using System.ComponentModel;
using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ServerPropertiesDialog : Window
{
    private readonly ServerPropertiesViewModel _viewModel;

    public ServerPropertiesDialog(ServerPropertiesViewModel viewModel)
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
