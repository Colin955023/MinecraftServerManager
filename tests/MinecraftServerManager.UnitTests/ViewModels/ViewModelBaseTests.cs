using System.Collections.ObjectModel;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.ViewModels;

public sealed class ViewModelBaseTests
{
    private sealed class TestUiService : IUiService
    {
        public string? LastErrorMessage { get; private set; }
        public string? LastErrorTitle { get; private set; }
        public bool PostToUiInvoked { get; private set; }



        public void RunOnUi(Action action) => throw new NotImplementedException();
        public T RunOnUi<T>(Func<T> func) => throw new NotImplementedException();
        public IUiTimer CreateUiTimer(TimeSpan interval, Action tickAction) => throw new NotImplementedException();
        public string? PickFolder(string? initialDirectory = null, string? title = null) => throw new NotImplementedException();
        public string? PickFile(string? filter = null, string? initialDirectory = null, string? title = null) => throw new NotImplementedException();
        public bool ShowConfirm(string message, string title = "確認", UiMessageLevel level = UiMessageLevel.Question) => throw new NotImplementedException();
        public void ShowInformation(string message, string title = "提示") => throw new NotImplementedException();
        public void ShowWarning(string message, string title = "警告") => throw new NotImplementedException();
        public void ShowError(string message, string title = "錯誤")
        {
            LastErrorMessage = message;
            LastErrorTitle = title;
        }
        public bool? ShowCreateServer(CreateServerViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowManageJava(ManageJavaViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowServerProperties(ServerPropertiesViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowServerMemory(ServerMemoryViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowModVersionPicker(ModVersionPickerViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowModInstallQueue(IEnumerable<ModInstallQueueItem> queue) => throw new NotImplementedException();
        public bool? ShowExportModList(ExportModListViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowRestoreBackup(RestoreBackupViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowImportServer(ImportServerViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowJvmArgsDialog(JvmArgsViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowPlayerManagementDialog(PlayerManagementViewModel viewModel) => throw new NotImplementedException();
        public IDisposable ShowProgress(string title, string initialStatus, out Action<int, string> reporter) => throw new NotImplementedException();
        public bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question) => throw new NotImplementedException();
        public void ShowToast(string message, string? title = null, ToastType type = ToastType.Info, int durationSeconds = 3) => throw new NotImplementedException();
        public void CopyToClipboard(string text) => throw new NotImplementedException();
        public void ActivateMainWindow() => throw new NotImplementedException();
        public void ShutdownApplication(int exitCode = 0) => throw new NotImplementedException();
        public void PostToUi(Action action, bool afterLayout = false)
        {
            PostToUiInvoked = true;
            action();
        }
        public IReadOnlyList<string>? PickFiles(string title, string filter, bool multiselect = false) => throw new NotImplementedException();
        public string? PickSaveFile(string title, string fileName, string filter) => throw new NotImplementedException();
        public bool? ShowJvmArgs(JvmArgsViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowPlayerManagement(PlayerManagementViewModel viewModel) => throw new NotImplementedException();
        public bool? ShowModInstallQueue(ObservableCollection<ModInstallQueueItem> queue) => throw new NotImplementedException();
        public IReadOnlyList<ModUpdateCandidateItem>? ShowModUpdates(IEnumerable<ModUpdateCandidateItem> items) => throw new NotImplementedException();
        public ServerDeleteDecision ShowServerDeleteConfirmation(string serverName, int backupCount) => throw new NotImplementedException();
        public void ShowExportModList(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher? launcher) => throw new NotImplementedException();
        public bool ShowServerInitialization(ServerConfig config, string javaPath, IServerRuntime runtime) => throw new NotImplementedException();
        public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel) => throw new NotImplementedException();
        public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份") => throw new NotImplementedException();
        public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName) => throw new NotImplementedException();
        public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName) => throw new NotImplementedException();
        public IOperationProgress ShowModOperationProgress(string title, string initialMessage) => throw new NotImplementedException();
    }

    [Fact]
    public async Task RunSafeAsync_WhenWorkSucceeds_CompletesWithoutErrors()
    {
        bool executed = false;
        await ViewModelBase.RunSafeAsync(() =>
        {
            executed = true;
            return Task.CompletedTask;
        }, "成功測試");

        Assert.True(executed);
    }

    [Fact]
    public async Task RunSafeAsync_WhenOperationCanceledExceptionThrown_SwallowsException()
    {
        var task = ViewModelBase.RunSafeAsync(() => throw new OperationCanceledException(), "取消測試");
        await task;

        Assert.True(task.IsCompletedSuccessfully);
    }

    [Fact]
    public async Task RunSafeAsync_WhenExceptionThrown_CatchesAndCallsOnException()
    {
        Exception? captured = null;
        var expectedEx = new InvalidOperationException("測試錯誤");

        await ViewModelBase.RunSafeAsync(
            () => Task.FromException(expectedEx),
            "失敗測試",
            onException: ex => captured = ex);

        Assert.Same(expectedEx, captured);
    }

    [Fact]
    public async Task RunSafeAsync_WhenNotifyUserIsTrue_InvokesUiServiceShowError()
    {
        var ui = new TestUiService();
        var expectedEx = new InvalidOperationException("嚴重失敗");

        await ViewModelBase.RunSafeAsync(
            () => Task.FromException(expectedEx),
            "使用者提示測試",
            uiService: ui,
            notifyUser: true);

        Assert.True(ui.PostToUiInvoked);
        Assert.NotNull(ui.LastErrorMessage);
        Assert.Contains("嚴重失敗", ui.LastErrorMessage);
        Assert.Equal("操作錯誤", ui.LastErrorTitle);
    }

    [Fact]
    public async Task RunSafeAsync_WhenOnExceptionThrows_DoesNotCrashCaller()
    {
        await ViewModelBase.RunSafeAsync(
            () => Task.FromException(new InvalidOperationException("初始錯誤")),
            "雙重異常測試",
            onException: _ => throw new InvalidOperationException("回呼異常"));
    }
}
