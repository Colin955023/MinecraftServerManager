using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用 UI 服務替身：不顯示視窗，確認一律同意</summary>
internal class NoOpUiService : IUiService
{
    public static readonly NoOpUiService Instance = new();

    public virtual Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question) =>
        Task.FromResult(true);

    public virtual Task<bool> ConfirmChoiceAsync(string message, string title, string primaryText, string closeText, UiMessageLevel level = UiMessageLevel.Question) =>
        Task.FromResult(true);

    public virtual Task<bool?> ConfirmYesNoCancelAsync(
        string message,
        string title,
        string yesText = "是",
        string noText = "否",
        string cancelText = "取消",
        UiMessageLevel level = UiMessageLevel.Question) =>
        Task.FromResult<bool?>(true);

    public virtual void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info) { }

    public virtual Task ShowErrorAsync(string message, string title) =>
        Task.CompletedTask;

    public void CopyToClipboard(string text) { }

    public virtual void ActivateMainWindow() { }

    public void ShutdownApplication(int exitCode = 0) { }

    public virtual void RestartApplication() { }

    public virtual void LaunchReplacementInstance(Action launch) => launch();

    public virtual void PostToUi(Action action, bool afterLayout = false) { }

    public virtual void RunOnUi(Action action) => action();

    public virtual IUiTimer CreateUiTimer(TimeSpan interval, Action tick) => new NoOpUiTimer();

    public virtual Task<IReadOnlyList<string>?> PickFilesAsync(string title, FileTypeChoice fileType, bool multiselect = false) =>
        Task.FromResult<IReadOnlyList<string>?>(null);

    public virtual Task<string?> PickSaveFileAsync(string title, string fileName, FileTypeChoice fileType) =>
        Task.FromResult<string?>(null);

    public virtual Task<string?> PickFolderAsync(string title, string? initialDirectory = null) =>
        Task.FromResult<string?>(null);

    public virtual Task<bool?> ShowManageJavaAsync(ManageJavaViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowJvmArgsAsync(JvmArgsViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowServerPropertiesAsync(ServerPropertiesViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowPlayerManagementAsync(PlayerManagementViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowRestoreBackupAsync(RestoreBackupViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowServerMemoryAsync(ServerMemoryViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowModVersionPickerAsync(ModVersionPickerViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<bool?> ShowModInstallQueueAsync(ModInstallQueueReviewViewModel viewModel) =>
        Task.FromResult<bool?>(null);

    public virtual Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(ModUpdateSelectionViewModel viewModel) =>
        Task.FromResult<IReadOnlyList<ModUpdateCandidateItem>?>(null);

    /// <summary>無介面時維持原本流程：不阻擋刪除，僅刪除伺服器本體</summary>
    public virtual Task<ServerDeleteDecision> ShowServerDeleteConfirmationAsync(string serverName, int backupCount) =>
        Task.FromResult(ServerDeleteDecision.DeleteServerOnly);

    public virtual Task<ModListExportFormat?> ShowExportModListAsync() =>
        Task.FromResult<ModListExportFormat?>(null);

    public virtual Task<bool> ShowServerInitializationAsync(ServerInitializationViewModel viewModel) =>
        Task.FromResult(true);

    public virtual IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel) => new NoOpMonitorWindow();

    public virtual IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, bool isRestore = false) =>
        new NoOpProgressSession<ServerBackupProgressReport>();

    public virtual IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName) =>
        new NoOpProgressSession<ServerImportProgressReport>();

    public virtual IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName) =>
        new NoOpProgressSession<ServerCreationProgressReport>();

    public virtual IOperationProgress ShowOperationProgress(string title, string initialMessage) =>
        new NoOpOperationProgress();

    private sealed class NoOpProgressSession<TReport> : IProgressSession<TReport>
    {
        public IProgress<TReport> Progress { get; } = new SynchronousProgress<TReport>(static _ => { });

        public void Dispose() { }
    }

    private sealed class NoOpOperationProgress : IOperationProgress
    {
        public void UpdateProgress(int current, int total, string message) { }

        public void Dispose() { }
    }

    private sealed class NoOpUiTimer : IUiTimer
    {
        public void StartTimer() { }

        public void StopTimer() { }

        public void Dispose() { }
    }

    private sealed class NoOpMonitorWindow : IMonitorWindow
    {
        public bool IsOpen => false;

        public event Action? Closed
        {
            add { }
            remove { }
        }

        public void BringToFront() { }

        public void Close() { }
    }
}
