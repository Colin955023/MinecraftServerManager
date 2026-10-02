using System.Windows.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ManageServerView : UserControl
{
    public ManageServerView()
    {
        InitializeComponent();
    }

    private void OnDataGridMouseDoubleClick(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if (DataContext is ManageServerViewModel vm && vm.ConfigureServerCommand.CanExecute(null))
        {
            vm.ConfigureServerCommand.Execute(null);
        }
    }

    private void OnViewPreviewMouseLeftButtonDown(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if (e.OriginalSource is System.Windows.DependencyObject dep)
        {
            if (FindVisualParent<Button>(dep) != null ||
                FindVisualParent<DataGridRow>(dep) != null ||
                FindVisualParent<System.Windows.Controls.Primitives.ScrollBar>(dep) != null ||
                FindVisualParent<System.Windows.Controls.Primitives.Thumb>(dep) != null ||
                FindVisualParent<TextBox>(dep) != null ||
                FindVisualParent<ComboBox>(dep) != null)
            {
                return;
            }
        }

        if (DataContext is ManageServerViewModel vm)
        {
            vm.SelectedServer = null;
        }
    }

    private static T? FindVisualParent<T>(System.Windows.DependencyObject? child) where T : System.Windows.DependencyObject
    {
        while (child != null)
        {
            if (child is T parent)
            {
                return parent;
            }

            child = System.Windows.Media.VisualTreeHelper.GetParent(child);
        }
        return null;
    }
}
