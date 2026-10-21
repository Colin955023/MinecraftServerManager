using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
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
    public string SizeFormatted { get; } = Core.Utilities.UnitFormatter.FormatBytes(sizeBytes);
    public string CreatedAtFormatted { get; } = createdAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
}

/// <summary>
/// 備份還原與管理對話方塊 ViewModel
/// </summary>
public sealed partial class RestoreBackupViewModel : ObservableObject
{
    private readonly IUiService _ui;

    private readonly IServerBackupService _backupService;
    private readonly string _serverName;
    private readonly string _backupDirectory;
    private readonly Func<bool>? _isServerRunningCheck;

    [ObservableProperty]
    public partial BackupDisplayItem? SelectedBackup { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsBusy { get; set; }

    public RestoreBackupViewModel(
        IServerBackupService backupService,
        string serverName,
        string? backupDirectory = null,
        Func<bool>? isServerRunningCheck = null,
        IUiService? uiService = null)
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _backupService = backupService;
        _serverName = serverName;
        _backupDirectory = backupDirectory ?? string.Empty;
        _isServerRunningCheck = isServerRunningCheck;
        WindowTitle = $"備份還原 — {serverName}";
        Backups = [];

        _ = RefreshBackupsAsync();
    }

    public string WindowTitle { get; }

    public BulkObservableCollection<BackupDisplayItem> Backups { get; }

    public event Action<bool>? RequestClose;

    [RelayCommand]
    public async Task RefreshBackupsAsync()
    {
        IsBusy = true;
        StatusMessage = "正在讀取備份清單...";
        try
        {
            var list = await _backupService.ListBackupsAsync(_serverName, _backupDirectory).ConfigureAwait(true);
            var displayItems = list.Select(static b => new BackupDisplayItem(b.FileName, b.SizeBytes, b.CreatedAt));
            Backups.ReplaceAll(displayItems);

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
            _ui.ShowToast("伺服器正在執行中，請先停止伺服器後再進行備份還原。", "無法還原", ToastType.Warning);
            return;
        }

        if (!_ui.Confirm(
            $"確定要將備份「{SelectedBackup.FileName}」還原至伺服器「{_serverName}」嗎？\n\n⚠️ 此操作將以備份內容覆蓋現有伺服器檔案，且無法復原。",
            "確認還原備份",
            UiMessageLevel.Warning))
        {
            return;
        }

        IsBusy = true;
        StatusMessage = $"正在還原備份「{SelectedBackup.FileName}」...";

        var progressDialog = _ui.ShowServerBackupProgress(_serverName, "還原");

        try
        {
            bool success = await _backupService.RestoreBackupAsync(
                _serverName,
                SelectedBackup.FileName,
                _backupDirectory,
                progressDialog.Progress).ConfigureAwait(true);

            progressDialog.Complete();

            if (success)
            {
                _ui.ShowToast($"伺服器「{_serverName}」已成功還原備份「{SelectedBackup.FileName}」！", "還原完成", ToastType.Success);
                RequestClose?.Invoke(true);
            }
            else
            {
                StatusMessage = "還原失敗，伺服器資料未變更";
                _ui.ShowWarning("還原失敗，伺服器檔案未變更。", "還原失敗");
            }
        }
        catch (Exception ex)
        {
            progressDialog.Complete();
            StatusMessage = $"還原異常：{ex.Message}";
            _ui.ShowWarning($"還原過程發生未預期異常：{ex.Message}", "還原異常");
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
        if (!_ui.Confirm(
            $"確定要永久刪除備份檔案「{toDelete.FileName}」嗎？\n此操作無法復原。",
            "確認刪除備份",
            UiMessageLevel.Warning))
        {
            return;
        }

        IsBusy = true;
        try
        {
            bool success = await _backupService.DeleteBackupAsync(_serverName, toDelete.FileName, _backupDirectory).ConfigureAwait(true);
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
