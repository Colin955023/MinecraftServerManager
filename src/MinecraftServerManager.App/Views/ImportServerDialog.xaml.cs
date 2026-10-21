using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ImportServerDialog : Window
{
    public ImportServerDialog(ImportServerViewModel viewModel)
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
