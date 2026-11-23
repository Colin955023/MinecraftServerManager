using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>備份還原與管理視窗</summary>
public sealed partial class RestoreBackupWindow : Window
{
    public RestoreBackupWindow(RestoreBackupViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(this, "備份還原與管理", 720, 520, Bindings.StopTracking, ViewModel, sortTargets: HeaderSort);
    }

    public RestoreBackupViewModel ViewModel { get; }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<BackupDisplayItem>(() => ViewModel.Backups, TableSortKeys.Backups);
}
