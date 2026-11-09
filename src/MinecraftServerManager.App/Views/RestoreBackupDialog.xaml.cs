using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 備份還原與管理視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class RestoreBackupDialog : Window
{
    public RestoreBackupViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public RestoreBackupDialog(RestoreBackupViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        Title = "備份還原與管理";

        WindowLayoutHelper.ResizeToDip(this, 720, 520);

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            Close();
        };
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Backups.SortBy(TableSortKeys.Backups, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Backups, TableSortKeys.Backups);
}
