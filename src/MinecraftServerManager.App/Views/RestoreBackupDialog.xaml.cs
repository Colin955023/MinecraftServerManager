using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

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

        AppWindow.Resize(new Windows.Graphics.SizeInt32(720, 520));

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            Close();
        };
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.Backups.Count <= 1)
        {
            return;
        }

        ViewModel.Backups.SortBy(e);
    }

    private void OnHeaderAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.Backups.Count == 0)
        {
            return;
        }

        var cols = BackupListColumns.Current;
        switch (propertyName)
        {
            case "FileName":
                cols.FileNameWidth = new(SortableTableHeader.CalculateAutoFitWidth(BackupListColumns.DefaultFileNameWidth, ViewModel.Backups.Select(b => b.FileName), "備份檔案名稱"));
                break;
            case "SizeFormatted":
                cols.SizeWidth = new(SortableTableHeader.CalculateAutoFitWidth(BackupListColumns.DefaultSizeWidth, ViewModel.Backups.Select(b => b.SizeFormatted), "檔案大小"));
                break;
            case "CreatedAtFormatted":
                cols.CreatedWidth = new(SortableTableHeader.CalculateAutoFitWidth(BackupListColumns.DefaultCreatedWidth, ViewModel.Backups.Select(b => b.CreatedAtFormatted), "建立時間"));
                break;
        }
    }
}
