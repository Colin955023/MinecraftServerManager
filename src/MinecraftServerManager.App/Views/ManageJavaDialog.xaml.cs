using System.Windows;
using System.Windows.Input;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ManageJavaDialog : Window
{
    private readonly ManageJavaViewModel _viewModel;

    public ManageJavaDialog(ManageJavaViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = _viewModel;
        _viewModel.RequestClose += () =>
        {
            DialogResult = true;
            Close();
        };
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void DataGrid_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (_viewModel.SelectedJava is not null)
        {
            _viewModel.Apply();
        }
    }
}
