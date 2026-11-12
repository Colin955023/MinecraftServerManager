using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器管理頁：伺服器存放根目錄變更與資料遷移</summary>
public sealed partial class ServersRootViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServersRootViewModel));

    private readonly IUiService _ui;
    private readonly SettingsManager _settingsManager;
    private readonly IServersRootService _rootService;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ILocalFileSystem _fileSystem;
    private readonly ServerListViewModel _list;

    public ServersRootViewModel(
        SettingsManager settingsManager,
        IServersRootService rootService,
        IServerRuntimeHost runtimeHost,
        ILocalFileSystem fileSystem,
        ServerListViewModel list,
        IUiService uiService)
    {
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(rootService);
        ArgumentNullException.ThrowIfNull(runtimeHost);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(list);

        _ui = uiService;
        _settingsManager = settingsManager;
        _rootService = rootService;
        _runtimeHost = runtimeHost;
        _fileSystem = fileSystem;
        _list = list;
    }

    [RelayCommand]
    public async Task ChangeServersRootAsync()
    {
        if (_runtimeHost.IsAnyRunning)
        {
            _ui.ShowNotification("目前有伺服器正在執行中，請先停止伺服器後再修改存放路徑。", "無法修改路徑", NotificationType.Warning);
            return;
        }

        string currentPath = _list.ResolveServersDirectory();
        string? pickedFolder = await _ui.PickFolderAsync("選擇伺服器存放主資料夾", _fileSystem.DirectoryExists(currentPath) ? currentPath : null).ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(pickedFolder))
        {
            return;
        }

        var check = _rootService.ValidateTargetRoot(currentPath, pickedFolder);
        switch (check.Result)
        {
            case RelocationPathCheckResult.SameAsCurrent:
                return;

            case RelocationPathCheckResult.TargetIsFile:
            case RelocationPathCheckResult.EmptyTarget:
                _ui.ShowNotification("所選路徑不是有效的資料夾。", "路徑無效", NotificationType.Warning);
                return;
        }

        string normalizedCurrent = check.NormalizedCurrent;
        string normalizedNew = check.NormalizedNew;

        // 新路徑一律為「所選資料夾\servers」；位於原路徑內時無法遷移，僅修改設定並保留原處資料
        bool hasContent = await _rootService.HasStoredContentAsync(normalizedCurrent).ConfigureAwait(true);
        if (!hasContent || check.Result == RelocationPathCheckResult.SubdirectoryOfCurrent)
        {
            await ApplySettingOnlyAsync(normalizedNew, $"伺服器存放路徑已更新為：\n{normalizedNew}\n\n應用程式將重新啟動以套用新路徑設定。").ConfigureAwait(true);
            return;
        }

        bool? decision = await _ui.ConfirmYesNoCancelAsync(
            $"偵測到原路徑已有存放伺服器或檔案：\n{normalizedCurrent}\n\n是否要將存放資料遷移至新路徑？\n{normalizedNew}\n\n• 選擇「是，遷移資料」：將原路徑內所有資料搬移至新路徑（新路徑必須為空資料夾）\n• 選擇「否，僅改設定」：保留原處資料不動，直接修改設定路徑\n• 選擇「取消」：取消操作不做任何變更",
            "是否遷移伺服器資料",
            "是，遷移資料",
            "否，僅改設定",
            "取消").ConfigureAwait(true);

        if (decision is null)
        {
            return;
        }

        if (decision == false)
        {
            await ApplySettingOnlyAsync(normalizedNew, $"伺服器存放路徑已更新為：\n{normalizedNew}\n（原路徑資料已保留於原處）\n\n應用程式將重新啟動以套用新路徑設定。").ConfigureAwait(true);
            return;
        }

        bool isTargetEmpty = await _rootService.IsTargetDirectoryEmptyAsync(normalizedNew).ConfigureAwait(true);
        if (!isTargetEmpty)
        {
            _ui.ShowNotification(
                $"目標資料夾不是空的，無法執行資料遷移：\n{normalizedNew}\n\n為避免檔案覆蓋衝突（或上層目錄包含舊目錄本身），遷移目標必須為空資料夾。\n請選擇一個空資料夾，或重新操作並選擇「否，僅改設定」。",
                "目標資料夾非空",
                NotificationType.Warning);
            return;
        }

        try
        {
            using (var progressDialog = _ui.ShowModOperationProgress("遷移伺服器存放資料", "正在準備遷移伺服器資料..."))
            {
                var progress = new Progress<(int Percent, string Message)>(report =>
                    progressDialog.UpdateProgress(report.Percent, 100, report.Message));

                await _rootService.RelocateAllContentAsync(normalizedCurrent, normalizedNew, progress).ConfigureAwait(true);
            }

            _settingsManager.SetExactServersRoot(normalizedNew);
            _list.DetectPath = normalizedNew;

            await _ui.ConfirmAsync(
                $"伺服器資料已成功遷移至新路徑：\n{normalizedNew}\n\n應用程式將重新啟動以套用新路徑設定。",
                "遷移完成",
                UiMessageLevel.Information).ConfigureAwait(true);
            await RestartAfterRootChangeAsync().ConfigureAwait(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "遷移伺服器存放資料失敗");
            await _ui.ShowErrorAsync($"遷移伺服器存放資料失敗（已自動復原原路徑資料）：\n{ex.Message}", "遷移失敗").ConfigureAwait(true);
        }
    }

    /// <summary>僅修改存放路徑設定（不搬移資料）並重新啟動應用程式</summary>
    private async Task ApplySettingOnlyAsync(string normalizedNew, string confirmMessage)
    {
        try
        {
            _settingsManager.SetExactServersRoot(normalizedNew);
            _list.DetectPath = normalizedNew;
            await _ui.ConfirmAsync(confirmMessage, "路徑已更新", UiMessageLevel.Information).ConfigureAwait(true);
            await RestartAfterRootChangeAsync().ConfigureAwait(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "修改伺服器存放路徑失敗");
            await _ui.ShowErrorAsync($"修改伺服器存放路徑失敗：\n{ex.Message}", "修改失敗").ConfigureAwait(true);
        }
    }

    /// <summary>路徑設定（含資料遷移）已完成後重新啟動；重新啟動失敗不代表遷移失敗，需明確告知使用者手動重新開啟</summary>
    private async Task RestartAfterRootChangeAsync()
    {
        try
        {
            _ui.RestartApplication();
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "重新啟動應用程式失敗");
            await _ui.ShowErrorAsync(
                $"新路徑設定已儲存，但無法自動重新啟動：\n{ex.Message}\n\n請關閉後手動重新開啟程式以套用新路徑。",
                "重新啟動失敗").ConfigureAwait(true);
        }
    }
}
