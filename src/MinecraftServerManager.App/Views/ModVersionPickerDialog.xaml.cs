using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ModVersionPickerDialog : Window
{
    public ModVersionPickerDialog(ModVersionPickerViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;

        if (Icon == null)
        {
            try
            {
                Icon = System.Windows.Media.Imaging.BitmapFrame.Create(
                    new Uri("pack://application:,,,/MinecraftServerManager.App;component/assets/icon.ico", UriKind.RelativeOrAbsolute));
            }
            catch
            {
            }
        }

        viewModel.RequestClose += success =>
        {
            DialogResult = success;
            Close();
        };
    }
}
