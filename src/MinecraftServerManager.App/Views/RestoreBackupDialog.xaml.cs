using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>備份還原與管理視窗（原生模態視窗，透過 ModalWindowHost 裝載）</summary>
public sealed partial class RestoreBackupDialog : Window
{
    public RestoreBackupViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public RestoreBackupDialog(RestoreBackupViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "備份還原與管理", 720, 520, Bindings.StopTracking);

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            ModalWindowHost.CloseDeferred(this);
        };
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Backups.SortBy(TableSortKeys.Backups, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Backups, TableSortKeys.Backups);
}
