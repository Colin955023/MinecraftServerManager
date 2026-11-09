using System.Collections.ObjectModel;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 訊息對話方塊的嚴重程度
/// </summary>
public enum UiMessageLevel
{
    Question,
    Information,
    Warning,
    Error,
}

/// <summary>
/// 系統提示嚴重程度
/// </summary>
public enum NotificationLevel
{
    Warning,
    Error,
}

/// <summary>
/// 刪除伺服器確認結果列舉
/// </summary>
public enum ServerDeleteDecision
{
    Cancel,
    DeleteServerOnly,
    DeleteServerAndBackups,
}

/// <summary>
/// 進度視窗工作階段：提供進度回報器，並於工作結束時關閉視窗
/// </summary>
public interface IProgressSession<TReport>
{
    public IProgress<TReport> Progress { get; }

    /// <summary>
    /// 標示工作已完成並關閉視窗
    /// </summary>
    public void Complete();
}

/// <summary>
/// 通用作業進度視窗控制點
/// </summary>
public interface IOperationProgress
{
    public void UpdateProgress(int current, int total, string message);

    public void Close();
}

/// <summary>
/// 非模態監控視窗控制點
/// </summary>
public interface IMonitorWindow
{
    public bool IsOpen { get; }

    public event Action? Closed;

    public void BringToFront();
}

/// <summary>
/// 所有使用者介面互動（訊息框、檔案選取、對話方塊、進度與視窗）的抽象。
/// ViewModel 僅相依此介面，具體實作位於 <see cref="WinUiService"/>。
/// </summary>
public interface IUiService
{
    public Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question);

    /// <summary>
    /// 顯示「是 / 否 / 取消」三鍵確認對話方塊；「是」回傳 true、「否」回傳 false、「取消」或關閉回傳 null
    /// </summary>
    public Task<bool?> ConfirmYesNoCancelAsync(
        string message,
        string title,
        string yesText = "是",
        string noText = "否",
        string cancelText = "取消",
        UiMessageLevel level = UiMessageLevel.Question);

    /// <summary>
    /// 於螢幕右下角顯示非阻塞式浮動提示（Toast），自動淡出
    /// </summary>
    public void ShowToast(string message, string? title = null, ToastType type = ToastType.Info, int durationSeconds = 3);

    public Task ShowWarningAsync(string message, string title);

    public Task ShowErrorAsync(string message, string title);

    public void CopyToClipboard(string text);

    /// <summary>
    /// 將主視窗還原並帶到前景
    /// </summary>
    public void ActivateMainWindow();

    /// <summary>
    /// 關閉應用程式並指定結束代碼
    /// </summary>
    public void ShutdownApplication(int exitCode = 0);

    /// <summary>
    /// 重新啟動應用程式
    /// </summary>
    public void RestartApplication();

    /// <summary>
    /// 以非阻塞方式於 UI 執行緒執行動作；非 UI 環境時不執行
    /// </summary>
    public void PostToUi(Action action, bool afterLayout = false);

    /// <summary>
    /// 已在 UI 執行緒則直接執行，否則派送至 UI 執行緒；非 UI 環境時直接執行
    /// </summary>
    public void RunOnUi(Action action);

    /// <summary>
    /// 建立於 UI 執行緒觸發的計時器
    /// </summary>
    public IUiTimer CreateUiTimer(TimeSpan interval, Action tick);

    /// <summary>
    /// 選取檔案；取消時回傳 null
    /// </summary>
    public Task<IReadOnlyList<string>?> PickFilesAsync(string title, string filter, bool multiselect = false);

    public Task<string?> PickSaveFileAsync(string title, string fileName, string filter);

    public Task<string?> PickFolderAsync(string title, string? initialDirectory = null);

    public Task<bool?> ShowManageJavaAsync(ManageJavaViewModel viewModel);

    public Task<bool?> ShowJvmArgsAsync(JvmArgsViewModel viewModel);

    public Task<bool?> ShowServerPropertiesAsync(ServerPropertiesViewModel viewModel);

    public Task<bool?> ShowPlayerManagementAsync(PlayerManagementViewModel viewModel);

    public Task<bool?> ShowRestoreBackupAsync(RestoreBackupViewModel viewModel);

    public Task<bool?> ShowServerMemoryAsync(ServerMemoryViewModel viewModel);

    public Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel);

    public Task<bool?> ShowModVersionPickerAsync(ModVersionPickerViewModel viewModel);

    public Task<bool?> ShowModInstallQueueAsync(ObservableCollection<ModInstallQueueItem> queue);

    /// <summary>
    /// 顯示模組更新清單；使用者確認時回傳所選項目，取消時回傳 null
    /// </summary>
    public Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(IEnumerable<ModUpdateCandidateItem> items);

    public Task<ServerDeleteDecision> ShowServerDeleteConfirmationAsync(string serverName, int backupCount);

    public Task ShowExportModListAsync(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher? launcher);

    /// <summary>
    /// 顯示初次啟動初始化對話方塊，回傳是否成功完成初始化
    /// </summary>
    public Task<bool> ShowServerInitializationAsync(ServerConfig config, string javaPath, IServerRuntime runtime);

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel);

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份");

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName);

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName);

    public IOperationProgress ShowModOperationProgress(string title, string initialMessage);
}
