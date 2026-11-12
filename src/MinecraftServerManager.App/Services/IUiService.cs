using System.Collections.ObjectModel;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.Services;

/// <summary>訊息對話方塊的嚴重程度</summary>
public enum UiMessageLevel
{
    Question,
    Information,
    Warning,
    Error,
}

/// <summary>刪除伺服器確認結果列舉</summary>
public enum ServerDeleteDecision
{
    Cancel,
    DeleteServerOnly,
    DeleteServerAndBackups,
}

/// <summary>進度視窗工作階段：提供進度回報器；<see cref="IDisposable.Dispose"/> 時關閉視窗（可重複呼叫）</summary>
public interface IProgressSession<TReport> : IDisposable
{
    public IProgress<TReport> Progress { get; }
}

/// <summary>通用作業進度視窗控制點；<see cref="IDisposable.Dispose"/> 時關閉視窗（可重複呼叫）</summary>
public interface IOperationProgress : IDisposable
{
    public void UpdateProgress(int current, int total, string message);
}

/// <summary>非模態監控視窗控制點</summary>
public interface IMonitorWindow
{
    public bool IsOpen { get; }

    public event Action? Closed;

    public void BringToFront();

    public void Close();
}

/// <summary>使用者介面互動抽象（ViewModel 僅相依此介面）</summary>
public interface IUiService
{
    public Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question);

    /// <summary>顯示兩鍵確認對話方塊；主要按鈕回傳 true，次要按鈕或關閉回傳 false</summary>
    public Task<bool> ConfirmChoiceAsync(string message, string title, string primaryText, string closeText, UiMessageLevel level = UiMessageLevel.Question);

    /// <summary>顯示三鍵確認對話方塊；是回傳 true、否回傳 false、取消或關閉回傳 null</summary>
    public Task<bool?> ConfirmYesNoCancelAsync(
        string message,
        string title,
        string yesText = "是",
        string noText = "否",
        string cancelText = "取消",
        UiMessageLevel level = UiMessageLevel.Question);

    /// <summary>通知提示唯一入口：資訊、成功與警告以右上角 InfoBar 顯示並自動關閉；錯誤以對話方塊顯示</summary>
    public void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info);

    public Task ShowErrorAsync(string message, string title);

    public void CopyToClipboard(string text);

    public void ActivateMainWindow();

    public void ShutdownApplication(int exitCode = 0);

    public void RestartApplication();

    /// <summary>以非阻塞方式於 UI 執行緒執行動作；非 UI 環境時不執行</summary>
    public void PostToUi(Action action, bool afterLayout = false);

    /// <summary>已在 UI 執行緒則直接執行，否則派送至 UI 執行緒；非 UI 環境時直接執行</summary>
    public void RunOnUi(Action action);

    public IUiTimer CreateUiTimer(TimeSpan interval, Action tick);

    /// <summary>選取檔案；取消時回傳 null</summary>
    public Task<IReadOnlyList<string>?> PickFilesAsync(string title, FileTypeChoice fileType, bool multiselect = false);

    public Task<string?> PickSaveFileAsync(string title, string fileName, FileTypeChoice fileType);

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

    /// <summary>顯示模組更新清單；使用者確認時回傳所選項目，取消時回傳 null</summary>
    public Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(IEnumerable<ModUpdateCandidateItem> items);

    public Task<ServerDeleteDecision> ShowServerDeleteConfirmationAsync(string serverName, int backupCount);

    public Task ShowExportModListAsync(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher launcher);

    /// <summary>顯示初次啟動初始化對話方塊，回傳是否成功完成初始化</summary>
    public Task<bool> ShowServerInitializationAsync(ServerInitializationViewModel viewModel);

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel);

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份");

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName);

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName);

    public IOperationProgress ShowModOperationProgress(string title, string initialMessage);
}
