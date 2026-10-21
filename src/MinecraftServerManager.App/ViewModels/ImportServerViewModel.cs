using MinecraftServerManager.App.Services;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 匯入伺服器對話方塊 ViewModel
/// </summary>
public sealed partial class ImportServerViewModel(IServerManager serverManager,
    IUiService? uiService = null) : ObservableObject
{
    private readonly IUiService _ui = uiService ?? NoOpUiService.Instance;

    private readonly IServerManager _serverManager = serverManager;

    [ObservableProperty]
    public partial string SourcePath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string ServerName { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotBusy))]
    public partial bool IsBusy { get; set; }

    public bool IsNotBusy => !IsBusy;

    public string? ImportedServerName { get; private set; }

    public event Action<bool>? RequestClose;

    [RelayCommand]
    public void BrowseZip()
    {
        if (_ui.PickFiles("選取 Minecraft 伺服器 ZIP 壓縮檔", "ZIP 壓縮檔 (*.zip)|*.zip|所有檔案 (*.*)|*.*") is { Count: > 0 } picked)
        {
            SourcePath = picked[0];
            ServerName = Path.GetFileNameWithoutExtension(picked[0]);
        }
    }

    [RelayCommand]
    public void BrowseFolder()
    {
        if (_ui.PickFolder("選取 Minecraft 伺服器目錄") is { } folder)
        {
            SourcePath = folder;
            ServerName = Path.GetFileName(folder);
        }
    }

    [RelayCommand]
    public async Task ImportAsync()
    {
        if (string.IsNullOrWhiteSpace(SourcePath))
        {
            StatusMessage = "請先選取來源目錄或 ZIP 壓縮檔";
            return;
        }

        if (string.IsNullOrWhiteSpace(ServerName))
        {
            StatusMessage = "請輸入匯入後的伺服器名稱";
            return;
        }

        IsBusy = true;
        StatusMessage = string.Empty;

        string targetName = ServerName.Trim();
        string source = SourcePath.Trim();

        // 開啟獨立進度視窗並在背景非同步執行匯入
        var progressDialog = _ui.ShowServerImportProgress(targetName);
        var progress = progressDialog.Progress;

        try
        {
            var result = await _serverManager.ImportServerAsync(
                source,
                targetName,
                ImportTransferMode.Copy,
                progress).ConfigureAwait(true);

            progressDialog.Complete();

            if (result.Completed)
            {
                ImportedServerName = targetName;
                RequestClose?.Invoke(true);
            }
            else
            {
                StatusMessage = $"匯入失敗：{result.Message}";
                _ui.ShowWarning($"匯入伺服器被拒絕或失敗：\n{result.Message}", "匯入伺服器失敗");
            }
        }
        catch (Exception ex)
        {
            progressDialog.Complete();
            StatusMessage = $"匯入異常：{ex.Message}";
            _ui.ShowError($"匯入伺服器時發生錯誤：\n{ex.Message}", "匯入伺服器異常");
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);
}
