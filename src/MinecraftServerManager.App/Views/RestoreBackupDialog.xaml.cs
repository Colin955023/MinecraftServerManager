using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>備份還原與管理視窗</summary>
public sealed partial class RestoreBackupDialog : Window
{
    public RestoreBackupViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public RestoreBackupDialog(RestoreBackupViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "備份還原與管理", 720, 520, Bindings.StopTracking);

        ViewModel.RequestClose += ModalWindowHost.CloseWithResult(this, success => DialogResult = success);
    }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<BackupDisplayItem>(() => ViewModel.Backups, TableSortKeys.Backups);
}
