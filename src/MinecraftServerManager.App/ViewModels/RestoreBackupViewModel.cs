using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>備份項目展示模型</summary>
public sealed class BackupDisplayItem(string fileName, long sizeBytes, DateTimeOffset createdAt)
{
    public string FileName { get; } = fileName;
    public long SizeBytes { get; } = sizeBytes;
    public long CreatedAtTicks { get; } = createdAt.UtcTicks;
    public string SizeFormatted { get; } = Core.Utilities.UnitFormatter.FormatBytes(sizeBytes);
    public string CreatedAtFormatted { get; } = createdAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
}

/// <summary>備份還原與管理對話方塊 ViewModel</summary>
public sealed partial class RestoreBackupViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(RestoreBackupViewModel));
    private readonly IUiService _ui;

    private readonly IServerBackupService _backupService;
    private readonly string _serverName;
    private readonly string _backupDirectory;
    private readonly Func<bool> _isServerRunningCheck;

    [ObservableProperty]
    public partial BackupDisplayItem? SelectedBackup { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    public RestoreBackupViewModel(
        IServerBackupService backupService,
        string serverName,
        IUiService uiService,
        string? backupDirectory,
        Func<bool> isServerRunningCheck)
    {
        ArgumentNullException.ThrowIfNull(isServerRunningCheck);
        _ui = uiService;
        _backupService = backupService;
        _serverName = serverName;
        _backupDirectory = backupDirectory ?? string.Empty;
        _isServerRunningCheck = isServerRunningCheck;
        Backups = [];

        _ = RunSafeAsync(RefreshBackupsAsync, "重新整理備份清單", Logger);
    }

    public BulkObservableCollection<BackupDisplayItem> Backups { get; }

    public event Action<bool>? RequestClose;

    public async Task RefreshBackupsAsync()
    {
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
        catch (OperationCanceledException)
        {
            Logger.Information("備份操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "讀取備份清單失敗");
            StatusMessage = $"讀取備份失敗：{ex.Message}";
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

        if (_isServerRunningCheck())
        {
            StatusMessage = "伺服器正在執行中，無法還原備份！請先停止伺服器。";
            _ui.ShowNotification("伺服器正在執行中，請先停止伺服器後再還原備份。", "無法還原", NotificationType.Warning);
            return;
        }

        if (!await _ui.ConfirmAsync(
            $"確定要將備份「{SelectedBackup.FileName}」還原至伺服器「{_serverName}」嗎？\n\n⚠️ 此操作將以備份內容覆蓋現有伺服器檔案，且無法復原。",
            "確認還原備份",
            UiMessageLevel.Warning).ConfigureAwait(true))
        {
            return;
        }

        StatusMessage = $"正在還原備份「{SelectedBackup.FileName}」...";

        try
        {
            bool success;
            using (var progressDialog = _ui.ShowServerBackupProgress(_serverName, "還原"))
            {
                success = await _backupService.RestoreBackupAsync(
                    _serverName,
                    SelectedBackup.FileName,
                    _backupDirectory,
                    progressDialog.Progress).ConfigureAwait(true);
            }

            if (success)
            {
                _ui.ShowNotification($"伺服器「{_serverName}」已成功還原備份「{SelectedBackup.FileName}」！", "還原完成", NotificationType.Success);
                RequestClose?.Invoke(true);
            }
            else
            {
                StatusMessage = "還原失敗，伺服器資料未變更";
                await _ui.ShowErrorAsync("還原失敗，伺服器檔案未變更。", "還原失敗").ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            StatusMessage = "已取消備份還原操作";
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "還原備份失敗");
            StatusMessage = $"還原失敗：{ex.Message}";
            await _ui.ShowErrorAsync($"還原過程發生未預期例外：{ex.Message}", "還原失敗").ConfigureAwait(true);
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
        if (!await _ui.ConfirmAsync(
            $"確定要永久刪除備份檔案「{toDelete.FileName}」嗎？\n此操作無法復原。",
            "確認刪除備份",
            UiMessageLevel.Warning).ConfigureAwait(true))
        {
            return;
        }

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
        catch (OperationCanceledException)
        {
            Logger.Information("備份操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "刪除備份失敗");
            StatusMessage = $"刪除失敗：{ex.Message}";
            await _ui.ShowErrorAsync($"刪除備份失敗：{ex.Message}", "刪除失敗").ConfigureAwait(true);
        }
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);
}
