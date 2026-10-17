using System.Collections.ObjectModel;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 訊息對話方塊的嚴重程度（與 WPF 型別解耦）
/// </summary>
public enum UiMessageLevel
{
    Question,
    Information,
    Warning,
    Error,
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

    public void UpdateMessage(string message);

    public void Close();
}

/// <summary>
/// 模組作業進度視窗控制點
/// </summary>
public interface IModOperationProgress : IOperationProgress
{
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
/// ViewModel 僅依賴此介面，具體 WPF 實作位於 <see cref="WpfUiService"/>。
/// </summary>
public interface IUiService
{
    public bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question);

    public void ShowInfo(string message, string title);

    /// <summary>
    /// 於指定伺服器的監控視窗中顯示提示訊息，若監控視窗未開啟則回退至活動視窗，避免畫面焦點切換
    /// </summary>
    public void ShowMonitorInfo(string serverName, string message, string title);

    public void ShowWarning(string message, string title);

    public void ShowError(string message, string title);

    public void ShowNotificationPopup(string title, string message, NotificationLevel level);

    public void CopyToClipboard(string text);

    /// <summary>
    /// 將主視窗還原並帶到前景
    /// </summary>
    public void ActivateMainWindow();

    /// <summary>
    /// 以非阻塞方式於 UI 執行緒執行動作；非 UI 環境時不執行
    /// </summary>
    public void PostToUi(Action action);

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
    public IReadOnlyList<string>? PickFiles(string title, string filter, bool multiselect = false);

    public string? PickSaveFile(string title, string fileName, string filter);

    public string? PickFolder(string title, string? initialDirectory = null);

    public bool? ShowManageJava(ManageJavaViewModel viewModel);

    public bool? ShowJvmArgs(JvmArgsViewModel viewModel);

    public bool? ShowServerProperties(ServerPropertiesViewModel viewModel);

    public bool? ShowRestoreBackup(RestoreBackupViewModel viewModel);

    public bool? ShowServerMemory(ServerMemoryViewModel viewModel);

    public bool? ShowImportServer(ImportServerViewModel viewModel);

    public bool? ShowModVersionPicker(ModVersionPickerViewModel viewModel);

    public bool? ShowModInstallQueue(ObservableCollection<ModInstallQueueItem> queue);

    /// <summary>
    /// 顯示模組更新清單；使用者確認時回傳所選項目，取消時回傳 null
    /// </summary>
    public IReadOnlyList<ModUpdateCandidateItem>? ShowModUpdates(IEnumerable<ModUpdateCandidateItem> items);

    public ServerDeleteDecision ShowServerDeleteConfirmation(string serverName, int backupCount);

    public void ShowExportModList(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher? launcher);

    /// <summary>
    /// 顯示初次啟動初始化對話方塊，回傳是否成功完成初始化
    /// </summary>
    public bool ShowServerInitialization(ServerConfig config, string javaPath, IServerRuntime runtime);

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel);

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份");

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName);

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName);

    public IModOperationProgress ShowModOperationProgress(string title, string initialMessage);
    public IOperationProgress ShowOperationProgress(string title, string initialMessage);
}
