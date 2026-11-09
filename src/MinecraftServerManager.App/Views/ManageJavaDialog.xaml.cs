using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

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

        AppWindow.Resize(new Windows.Graphics.SizeInt32(820, 620));

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

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.InstalledJavas.Count <= 1)
        {
            return;
        }

        ViewModel.InstalledJavas.SortBy(e);
    }

    private void OnHeaderAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.InstalledJavas.Count == 0)
        {
            return;
        }

        var cols = JavaListColumns.Current;
        switch (propertyName)
        {
            case "MajorVersion":
                cols.VersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(JavaListColumns.DefaultVersionWidth, ViewModel.InstalledJavas.Select(j => j.DisplayName), "主要版本"));
                break;
            case "Vendor":
                cols.VendorWidth = new(SortableTableHeader.CalculateAutoFitWidth(JavaListColumns.DefaultVendorWidth, ViewModel.InstalledJavas.Select(j => j.Vendor), "發行廠商"));
                break;
            case "StatusText":
                cols.StatusWidth = new(SortableTableHeader.CalculateAutoFitWidth(JavaListColumns.DefaultStatusWidth, ViewModel.InstalledJavas.Select(j => j.StatusText), "相容狀態"));
                break;
            case "ExecutablePath":
                cols.PathWidth = new(SortableTableHeader.CalculateAutoFitWidth(JavaListColumns.DefaultPathWidth, ViewModel.InstalledJavas.Select(j => j.ExecutablePath), "執行檔路徑"));
                break;
        }
    }
}
