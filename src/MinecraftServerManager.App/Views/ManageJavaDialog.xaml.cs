using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>管理 Java 環境視窗（原生模態視窗，透過 ModalWindowHost 裝載）</summary>
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

    private void ListView_DoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e)
    {
        if (ViewModel.ApplyCommand.CanExecute(null))
        {
            ViewModel.ApplyCommand.Execute(null);
        }
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.InstalledJavas.SortBy(TableSortKeys.Javas, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.InstalledJavas, TableSortKeys.Javas);
}
