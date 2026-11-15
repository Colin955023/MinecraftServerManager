using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>管理 Java 環境視窗</summary>
public sealed partial class ManageJavaDialog : Window
{
    public ManageJavaViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ManageJavaDialog(ManageJavaViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "管理 Java 環境", 820, 620, Bindings.StopTracking);

        ViewModel.RequestClose += () =>
        {
            DialogResult = true;
            ModalWindowHost.CloseDeferred(this);
        };
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void ListView_DoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e) => ViewModel.ApplyCommand.TryExecute();

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<JavaItemViewModel>(() => ViewModel.InstalledJavas, TableSortKeys.Javas);
}
