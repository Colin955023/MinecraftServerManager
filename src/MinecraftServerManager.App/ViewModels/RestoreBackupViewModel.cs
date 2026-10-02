using System.Collections.ObjectModel;
using System.Globalization;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 備份項目展示模型
/// </summary>
public sealed class BackupDisplayItem(string fileName, long sizeBytes, DateTimeOffset createdAt)
{
    public string FileName { get; } = fileName;
    public string SizeFormatted { get; } = (sizeBytes / 1024.0 / 1024.0).ToString("F2", CultureInfo.InvariantCulture) + " MB";
    public string CreatedAtFormatted { get; } = createdAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
}

/// <summary>
/// 備份還原與管理對話框 ViewModel
/// </summary>
public sealed partial class RestoreBackupViewModel : ObservableObject
{
    private readonly IServerBackupService _backupService;
    private readonly string _serverName;
    private readonly string _backupDirectory;
    private readonly Func<bool>? _isServerRunningCheck;

    [ObservableProperty]
    private BackupDisplayItem? _selectedBackup;

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    private bool _isBusy;

    public RestoreBackupViewModel(
        IServerBackupService backupService,
        string serverName,
        string? backupDirectory = null,
        Func<bool>? isServerRunningCheck = null)
    {
        _backupService = backupService;
        _serverName = serverName;
        _backupDirectory = backupDirectory ?? string.Empty;
        _isServerRunningCheck = isServerRunningCheck;
        WindowTitle = $"備份還原 — {serverName}";
        Backups = [];

        _ = RefreshBackupsAsync();
    }

    public string WindowTitle { get; }

    public ObservableCollection<BackupDisplayItem> Backups { get; }

    public event Action<bool>? RequestClose;

    [RelayCommand]
    public async Task RefreshBackupsAsync()
    {
        IsBusy = true;
        StatusMessage = "正在讀取備份清單...";
        try
        {
            var list = await Task.Run(() => _backupService.ListBackupsAsync(_serverName, _backupDirectory)).ConfigureAwait(true);
            Backups.Clear();
            foreach (var b in list)
            {
                Backups.Add(new BackupDisplayItem(b.FileName, b.SizeBytes, b.CreatedAt));
            }

            if (Backups.Count > 0)
            {
                SelectedBackup = Backups[0];
                StatusMessage = $"共找到 {Backups.Count} 份備份";
            }
            else
            {
                StatusMessage = "此伺服器目前尚無任何備份檔案";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"讀取備份失敗：{ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public async Task RestoreAsync()
    {
        if (SelectedBackup is null)
        {
            StatusMessage = "請先選擇要還原的備份檔案";
            return;
        }

        if (_isServerRunningCheck?.Invoke() == true)
        {
            StatusMessage = "伺服器正在執行中，無法還原備份！請先停止伺服器。";
            Views.DialogHelper.ShowWarning("伺服器正在執行中，請先停止伺服器後再進行備份還原。", "無法還原");
            return;
        }

        if (!Views.DialogHelper.Confirm(
            $"確定要將備份「{SelectedBackup.FileName}」還原至伺服器「{_serverName}」嗎？\n\n⚠️ 此操作將以備份內容覆蓋現有伺服器檔案，且無法撤銷。",
            "確認還原備份",
            MessageBoxImage.Warning))
        {
            return;
        }

        IsBusy = true;
        StatusMessage = $"正在還原備份「{SelectedBackup.FileName}」...";
        try
        {
            bool success = await Task.Run(() => _backupService.RestoreBackupAsync(_serverName, SelectedBackup.FileName, _backupDirectory)).ConfigureAwait(true);
            if (success)
            {
                RequestClose?.Invoke(true);
            }
            else
            {
                StatusMessage = "還原失敗，伺服器資料未變更";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"還原異常：{ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public async Task DeleteAsync()
    {
        if (SelectedBackup is null)
        {
            StatusMessage = "請先選擇要刪除的備份檔案";
            return;
        }

        var toDelete = SelectedBackup;
        if (!Views.DialogHelper.Confirm(
            $"確定要永久刪除備份檔案「{toDelete.FileName}」嗎？\n此操作無法復原。",
            "確認刪除備份",
            MessageBoxImage.Warning))
        {
            return;
        }

        IsBusy = true;
        try
        {
            bool success = await Task.Run(() => _backupService.DeleteBackupAsync(_serverName, toDelete.FileName, _backupDirectory)).ConfigureAwait(true);
            if (success)
            {
                Backups.Remove(toDelete);
                SelectedBackup = Backups.FirstOrDefault();
                StatusMessage = $"已成功刪除備份：{toDelete.FileName}";
            }
            else
            {
                StatusMessage = "刪除備份失敗";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"刪除異常：{ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);
}
