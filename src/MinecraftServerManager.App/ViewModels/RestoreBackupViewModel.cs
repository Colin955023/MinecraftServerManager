using System.Collections.ObjectModel;
using System.Globalization;
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

    [ObservableProperty]
    private BackupDisplayItem? _selectedBackup;

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    private bool _isBusy;

    public RestoreBackupViewModel(IServerBackupService backupService, string serverName)
    {
        _backupService = backupService;
        _serverName = serverName;
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
            var list = await _backupService.ListBackupsAsync(_serverName).ConfigureAwait(true);
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

        IsBusy = true;
        StatusMessage = $"正在還原備份「{SelectedBackup.FileName}」...";
        try
        {
            bool success = await _backupService.RestoreBackupAsync(_serverName, SelectedBackup.FileName).ConfigureAwait(true);
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
        IsBusy = true;
        try
        {
            bool success = await _backupService.DeleteBackupAsync(_serverName, toDelete.FileName).ConfigureAwait(true);
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
