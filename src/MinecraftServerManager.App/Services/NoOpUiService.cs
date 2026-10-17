using System.Collections.ObjectModel;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 無介面的預設實作，供未注入 UI 服務時使用（例如單元測試）。行為與原本「沒有 Application 實例」時相同：不顯示任何視窗。
/// </summary>
public class NoOpUiService : IUiService
{
    public static readonly NoOpUiService Instance = new();

    public virtual bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question) => true;

    public virtual void ShowInfo(string message, string title) { }
    public virtual void ShowMonitorInfo(string serverName, string message, string title) => ShowInfo(message, title);

    public virtual void ShowWarning(string message, string title) { }

    public virtual void ShowError(string message, string title) { }

    public void ShowNotificationPopup(string title, string message, NotificationLevel level) { }

    public void CopyToClipboard(string text) { }

    public void ActivateMainWindow() { }

    public void PostToUi(Action action) { }

    public void RunOnUi(Action action) => action();

    public virtual IUiTimer CreateUiTimer(TimeSpan interval, Action tick) => new NoOpUiTimer();

    public IReadOnlyList<string>? PickFiles(string title, string filter, bool multiselect = false) => null;

    public string? PickSaveFile(string title, string fileName, string filter) => null;

    public string? PickFolder(string title, string? initialDirectory = null) => null;

    public bool? ShowManageJava(ManageJavaViewModel viewModel) => null;

    public bool? ShowJvmArgs(JvmArgsViewModel viewModel) => null;

    public bool? ShowServerProperties(ServerPropertiesViewModel viewModel) => null;

    public bool? ShowRestoreBackup(RestoreBackupViewModel viewModel) => null;

    public bool? ShowServerMemory(ServerMemoryViewModel viewModel) => null;

    public bool? ShowImportServer(ImportServerViewModel viewModel) => null;

    public bool? ShowModVersionPicker(ModVersionPickerViewModel viewModel) => null;

    public bool? ShowModInstallQueue(ObservableCollection<ModInstallQueueItem> queue) => null;

    public IReadOnlyList<ModUpdateCandidateItem>? ShowModUpdates(IEnumerable<ModUpdateCandidateItem> items) => null;

    /// <summary>
    /// 無介面時維持原本流程：不阻擋刪除，僅刪除伺服器本體
    /// </summary>
    public ServerDeleteDecision ShowServerDeleteConfirmation(string serverName, int backupCount) => ServerDeleteDecision.DeleteServerOnly;

    public void ShowExportModList(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher? launcher) { }

    public bool ShowServerInitialization(ServerConfig config, string javaPath, IServerRuntime runtime) => true;

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel) => new NoOpMonitorWindow();

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份") =>
        new NoOpProgressSession<ServerBackupProgressReport>();

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName) =>
        new NoOpProgressSession<ServerImportProgressReport>();

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName) =>
        new NoOpProgressSession<ServerCreationProgressReport>();

    public IModOperationProgress ShowModOperationProgress(string title, string initialMessage) => new NoOpModOperationProgress();

    public IOperationProgress ShowOperationProgress(string title, string initialMessage) => ShowModOperationProgress(title, initialMessage);

    private sealed class NoOpProgressSession<TReport> : IProgressSession<TReport>
    {
        public IProgress<TReport> Progress { get; } = new Progress<TReport>();

        public void Complete() { }
    }

    private sealed class NoOpModOperationProgress : IModOperationProgress
    {
        public void UpdateProgress(int current, int total, string message) { }

        public void UpdateMessage(string message) { }

        public void Close() { }
    }

    private sealed class NoOpUiTimer : IUiTimer
    {
        public void StartTimer() { }

        public void StopTimer() { }
    }

    private sealed class NoOpMonitorWindow : IMonitorWindow
    {
        public bool IsOpen => false;

        public event Action? Closed { add { } remove { } }

        public void BringToFront() { }
    }
}
