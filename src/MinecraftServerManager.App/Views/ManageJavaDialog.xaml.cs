using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 管理 Java 環境視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class ManageJavaDialog : Window
{
    public ManageJavaViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ManageJavaDialog(ManageJavaViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        Title = "管理 Java 環境";

        WindowLayoutHelper.ResizeToDip(this, 820, 620);

        ViewModel.RequestClose += () =>
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
