using MinecraftServerManager.App.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 匯入伺服器對話方塊 ViewModel
/// </summary>
public sealed partial class ImportServerViewModel(IServerManager serverManager,
    IUiService uiService) : ObservableObject
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ImportServerViewModel));
    private readonly IUiService _ui = uiService;
    private readonly IServerManager _serverManager = serverManager;

    [ObservableProperty]
    public partial string SourcePath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string ServerName { get; set; } = string.Empty;

    [ObservableProperty]
    public partial ImportTransferMode TransferMode { get; set; } = ImportTransferMode.Copy;

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsBusy { get; set; }

    public bool IsCopyMode
    {
        get => TransferMode == ImportTransferMode.Copy;
        set
        {
            if (value)
            {
                TransferMode = ImportTransferMode.Copy;
            }
        }
    }

    public bool IsMoveMode
    {
        get => TransferMode == ImportTransferMode.Move;
        set
        {
            if (value)
            {
                TransferMode = ImportTransferMode.Move;
            }
        }
    }

    public string? ImportedServerName { get; private set; }

    partial void OnTransferModeChanged(ImportTransferMode value)
    {
        OnPropertyChanged(nameof(IsCopyMode));
        OnPropertyChanged(nameof(IsMoveMode));
    }

    [RelayCommand]
    public async Task BrowseZipAsync()
    {
        if (await _ui.PickFilesAsync("選取 Minecraft 伺服器 ZIP 壓縮檔", FileTypeChoice.Zip).ConfigureAwait(true) is { Count: > 0 } picked)
        {
            SourcePath = picked[0];
            ServerName = Path.GetFileNameWithoutExtension(picked[0]);
        }
    }

    [RelayCommand]
    public async Task BrowseFolderAsync()
    {
        if (await _ui.PickFolderAsync("選取 Minecraft 伺服器目錄").ConfigureAwait(true) is { } folder)
        {
            SourcePath = folder;
            ServerName = Path.GetFileName(folder);
        }
    }

    /// <summary>
    /// 驗證輸入欄位是否合法有效
    /// </summary>
    public bool ValidateInputs()
    {
        if (string.IsNullOrWhiteSpace(SourcePath))
        {
            StatusMessage = "請先選取來源目錄或 ZIP 壓縮檔";
            return false;
        }

        if (string.IsNullOrWhiteSpace(ServerName))
        {
            StatusMessage = "請輸入匯入後的伺服器名稱";
            return false;
        }

        StatusMessage = string.Empty;
        return true;
    }

    /// <summary>
    /// 執行伺服器匯入核心流程並顯示獨立進度視窗
    /// </summary>
    public async Task<bool> ExecuteImportAsync()
    {
        if (!ValidateInputs())
        {
            return false;
        }

        string targetName = ServerName.Trim();
        string source = SourcePath.Trim();

        if (TransferMode == ImportTransferMode.Move)
        {
            bool confirmed = await _ui.ConfirmAsync(
                $"您選擇了「遷移」模式，匯入完成後將會移除原始來源：\n{source}\n\n確定要繼續遷移匯入嗎？",
                "確認遷移匯入",
                UiMessageLevel.Warning).ConfigureAwait(true);
            if (!confirmed)
            {
                return false;
            }
        }

        IsBusy = true;
        StatusMessage = string.Empty;

        try
        {
            ServerImportResult result;
            using (var progressDialog = _ui.ShowServerImportProgress(targetName))
            {
                result = await _serverManager.ImportServerAsync(
                    source,
                    targetName,
                    TransferMode,
                    progressDialog.Progress).ConfigureAwait(true);
            }

            if (result.Completed)
            {
                ImportedServerName = targetName;
                return true;
            }
            else
            {
                StatusMessage = $"匯入失敗：{result.Message}";
                await _ui.ShowErrorAsync($"匯入伺服器被拒絕或失敗：\n{result.Message}", "匯入伺服器失敗").ConfigureAwait(true);
                return false;
            }
        }
        catch (OperationCanceledException)
        {
            StatusMessage = "匯入已取消";
            return false;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "匯入伺服器異常: {Message}", ex.Message);
            StatusMessage = $"匯入異常：{ex.Message}";
            await _ui.ShowErrorAsync($"匯入伺服器時發生錯誤：\n{ex.Message}", "匯入伺服器異常").ConfigureAwait(true);
            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }
}
