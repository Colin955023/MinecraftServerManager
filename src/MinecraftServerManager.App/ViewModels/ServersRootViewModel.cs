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
    private readonly ISettingsManager _settingsManager;
    private readonly IServersRootService _rootService;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ILocalFileSystem _fileSystem;
    private readonly ServerListViewModel _list;

    public ServersRootViewModel(
        ISettingsManager settingsManager,
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
        ArgumentNullException.ThrowIfNull(uiService);

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
        if (!_ui.EnsureServerStopped(_runtimeHost.IsAnyRunning, "目前有伺服器正在執行中，請先停止伺服器後再修改存放路徑。", "無法修改路徑"))
        {
            return;
        }

        string currentPath = await _list.ResolveServersDirectoryAsync();
        string? pickedFolder = await _ui.PickFolderAsync("選擇伺服器存放主資料夾", await _fileSystem.DirectoryExistsAsync(currentPath) ? currentPath : null);
        if (string.IsNullOrWhiteSpace(pickedFolder))
        {
            return;
        }

        var check = await _rootService.ValidateTargetRootAsync(currentPath, pickedFolder);
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

        // 新路徑一律為「所選資料夾\servers」；位於原路徑內時只改設定
        bool hasContent = await _rootService.HasStoredContentAsync(normalizedCurrent);
        if (!hasContent || check.Result == RelocationPathCheckResult.SubdirectoryOfCurrent)
        {
            await ApplySettingOnlyAsync(normalizedNew, $"伺服器存放路徑已更新為：\n{normalizedNew}");
            return;
        }

        bool? decision = await _ui.ConfirmYesNoCancelAsync(
            $"偵測到原路徑已有存放伺服器或檔案：\n{normalizedCurrent}\n\n是否要將存放資料遷移至新路徑？\n{normalizedNew}\n\n• 選擇「是，遷移資料」：將原路徑內所有資料搬移至新路徑（新路徑必須為空資料夾）\n• 選擇「否，僅改設定」：保留原處資料不動，直接修改設定路徑\n• 選擇「取消」：取消操作不做任何變更",
            "是否遷移伺服器資料",
            "是，遷移資料",
            "否，僅改設定",
            "取消");

        if (decision is null)
        {
            return;
        }

        if (decision == false)
        {
            await ApplySettingOnlyAsync(normalizedNew, $"伺服器存放路徑已更新為：\n{normalizedNew}\n（原路徑資料已保留於原處）");
            return;
        }

        bool isTargetEmpty = await _rootService.IsTargetDirectoryEmptyAsync(normalizedNew);
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
            IReadOnlyList<string> leftovers;
            using (var progressDialog = _ui.ShowOperationProgress("遷移伺服器存放資料", "正在準備遷移伺服器資料..."))
            {
                var progress = progressDialog.CreateProgress();

                leftovers = await _rootService.RelocateAllContentAsync(normalizedCurrent, normalizedNew, progress);
            }

            await SaveServersRootAsync(normalizedNew);

            string leftoverNote = leftovers.Count == 0
                ? string.Empty
                : $"\n\n下列原位置項目已複製到新路徑，但無法刪除（可能被其他程式占用），請自行移除：\n{string.Join('\n', leftovers)}";
            await PromptRestartAsync($"伺服器資料已成功遷移至新路徑：\n{normalizedNew}{leftoverNote}", "遷移完成");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "遷移伺服器存放資料失敗");
            await _ui.ShowErrorAsync($"遷移伺服器存放資料失敗（已自動復原原路徑資料）：\n{ex.Message}", "遷移失敗");
        }
    }

    /// <summary>僅修改存放路徑設定（不搬移資料）並詢問是否重新啟動</summary>
    private async Task ApplySettingOnlyAsync(string normalizedNew, string message)
    {
        try
        {
            await SaveServersRootAsync(normalizedNew);
            await PromptRestartAsync(message, "路徑已更新");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "修改伺服器存放路徑失敗");
            await _ui.ShowErrorAsync($"修改伺服器存放路徑失敗：\n{ex.Message}", "修改失敗");
        }
    }

    /// <summary>於背景執行緒寫入設定檔後更新清單偵測路徑</summary>
    private async Task SaveServersRootAsync(string normalizedNew)
    {
        await Task.Run(() => _settingsManager.SetExactServersRoot(normalizedNew));
        _list.DetectPath = normalizedNew;
    }

    /// <summary>詢問是否立即重新啟動以套用新路徑；選擇稍後時提示下次啟動才完整套用</summary>
    private async Task PromptRestartAsync(string message, string title)
    {
        if (!await _ui.ConfirmChoiceAsync(
            $"{message}\n\n需重新啟動應用程式才能完整套用新路徑設定。",
            title,
            "立即重新啟動",
            "稍後",
            UiMessageLevel.Information))
        {
            _ui.Notify("新的伺服器存放路徑將於下次啟動應用程式後完整套用", NotificationType.Info);
            return;
        }

        try
        {
            _ui.RestartApplication();
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "重新啟動應用程式失敗");
            await _ui.ShowErrorAsync(
                $"新路徑設定已儲存，但無法自動重新啟動：\n{ex.Message}\n\n請關閉後手動重新開啟程式以套用新路徑。",
                "重新啟動失敗");
        }
    }
}
