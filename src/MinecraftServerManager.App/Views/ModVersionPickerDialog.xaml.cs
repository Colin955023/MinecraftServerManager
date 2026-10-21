using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ModVersionPickerDialog : Window
{
    public ModVersionPickerDialog(ModVersionPickerViewModel viewModel)
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
