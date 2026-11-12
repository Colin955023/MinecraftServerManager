using System.Collections.ObjectModel;
using System.Runtime.CompilerServices;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.ApplicationModel.DataTransfer;
using Microsoft.Windows.Storage.Pickers;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// <see cref="IUiService"/> 的 WinUI 3 原生實作。
/// 管理 ContentDialog 佇列（<see cref="DialogStackCoordinator"/>）、模態視窗宿主（<see cref="ModalWindowHost"/>）、
/// 檔案與資料夾選取器（透過 AppWindow.Id 繫結視窗）、UI 執行緒派送與計時器。
/// </summary>
public sealed partial class WinUiService : IUiService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(WinUiService));

    private readonly DispatcherQueue _dispatcherQueue;
    private readonly IProcessRunner _processRunner;
    private readonly List<Window> _windowStack = [];
    private readonly Lock _windowLock = new();
    private readonly ConditionalWeakTable<XamlRoot, DialogStackCoordinator> _coordinators = [];

    public Window? MainWindow { get; private set; }
    public ElementTheme CurrentTheme { get; set; } = ElementTheme.Default;

    public WinUiService(DispatcherQueue dispatcherQueue, IProcessRunner processRunner)
    {
        _dispatcherQueue = dispatcherQueue ?? throw new ArgumentNullException(nameof(dispatcherQueue));
        _processRunner = processRunner ?? throw new ArgumentNullException(nameof(processRunner));
        AccentColorService.SetUiDispatcher(RunOnUi);
        AccentColorService.AccentColorChanged += OnAccentColorChanged;
    }

    private void OnAccentColorChanged()
    {
        RunOnUi(() =>
        {
            lock (_windowLock)
            {
                foreach (var win in _windowStack)
                {
                    if (win.AppWindow is not null && win.Content is FrameworkElement fe)
                    {
                        var t = fe.RequestedTheme;
                        fe.RequestedTheme = t == ElementTheme.Light ? ElementTheme.Dark : ElementTheme.Light;
                        fe.RequestedTheme = t;
                        TitleBarThemeHelper.ApplyTitleBarTheme(win.AppWindow, CurrentTheme);
                    }
                }
            }
        });
    }

    public void RegisterMainWindow(Window mainWindow)
    {
        ArgumentNullException.ThrowIfNull(mainWindow);
        MainWindow = mainWindow;
        lock (_windowLock)
        {
            if (!_windowStack.Contains(mainWindow))
            {
                _windowStack.Add(mainWindow);
            }
        }
    }

    public Window CurrentActiveWindow
    {
        get
        {
            lock (_windowLock)
            {
                for (int i = _windowStack.Count - 1; i >= 0; i--)
                {
                    var top = _windowStack[i];
                    if (top.AppWindow is null)
                    {
                        _windowStack.RemoveAt(i);
                        continue;
                    }
                    return top;
                }
            }
            return MainWindow ?? throw new InvalidOperationException("目前無作用中的視窗。");
        }
    }

    public void PushWindow(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        lock (_windowLock)
        {
            _windowStack.Add(window);
        }
    }

    public void PopWindow(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        lock (_windowLock)
        {
            _windowStack.Remove(window);
        }
    }

    public DialogStackCoordinator GetCoordinator(XamlRoot xamlRoot) =>
        _coordinators.GetOrCreateValue(xamlRoot);

    public XamlRoot GetCurrentXamlRoot()
    {
        var window = CurrentActiveWindow;
        if (window.Content?.XamlRoot is { } root)
        {
            return root;
        }

        if (MainWindow?.Content?.XamlRoot is { } mainRoot)
        {
            return mainRoot;
        }

        throw new InvalidOperationException("無法取得作用中的 XamlRoot。");
    }

    /// <summary>將非同步 UI 作業派送至 UI 執行緒執行並等待結果（例外與取消皆原樣傳回呼叫端）</summary>
    private async Task<T> InvokeOnUiAsync<T>(Func<Task<T>> operation)
    {
        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        bool enqueued = _dispatcherQueue.TryEnqueue(async () =>
        {
            try
            {
                tcs.TrySetResult(await operation());
            }
            catch (Exception ex)
            {
                tcs.TrySetException(ex);
            }
        });

        if (!enqueued)
        {
            throw new InvalidOperationException("無法派送作業至 UI 執行緒。");
        }

        return await tcs.Task;
    }

    public async Task<ContentDialogResult> ShowContentDialogAsync(ContentDialog dialog, XamlRoot? preferredRoot = null)
    {
        ArgumentNullException.ThrowIfNull(dialog);

        if (!_dispatcherQueue.HasThreadAccess)
        {
            return await InvokeOnUiAsync(() => ShowContentDialogAsync(dialog, preferredRoot));
        }

        XamlRoot root = preferredRoot ?? GetCurrentXamlRoot();
        dialog.XamlRoot = root;
        dialog.RequestedTheme = CurrentTheme;

        // WinUI 同一執行緒同時只能開啟一個 ContentDialog（即使位於不同視窗），因此一律共用主視窗協調器排隊
        var coordinator = GetCoordinator(MainWindow?.Content?.XamlRoot ?? root);
        return await coordinator.ShowDialogAsync(
            () => dialog.ShowAsync().AsTask(),
            () =>
            {
                if (dialog is OperationProgressDialog progressDialog)
                {
                    progressDialog.HideForNestedDialog();
                }
                else
                {
                    dialog.Hide();
                }
            }
        );
    }

    public async Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question)
    {
        AudioFeedback.Play(level);
        var dialog = new CustomConfirmDialog(message, title, level);
        var result = await ShowContentDialogAsync(dialog);
        return result == ContentDialogResult.Primary;
    }

    public async Task<bool> ConfirmChoiceAsync(string message, string title, string primaryText, string closeText, UiMessageLevel level = UiMessageLevel.Question)
    {
        AudioFeedback.Play(level);
        var dialog = new CustomConfirmDialog(message, title, level, primaryText, null, closeText);
        var result = await ShowContentDialogAsync(dialog);
        return result == ContentDialogResult.Primary;
    }

    public async Task<bool?> ConfirmYesNoCancelAsync(
        string message,
        string title,
        string yesText = "是",
        string noText = "否",
        string cancelText = "取消",
        UiMessageLevel level = UiMessageLevel.Question)
    {
        AudioFeedback.Play(level);
        var dialog = new CustomConfirmDialog(message, title, level, yesText, noText, cancelText);
        var result = await ShowContentDialogAsync(dialog);
        return result switch
        {
            ContentDialogResult.Primary => true,
            ContentDialogResult.Secondary => false,
            _ => null,
        };
    }

    /// <summary>通知提示唯一入口：資訊、成功與警告以 InfoBar 浮動顯示，錯誤以對話方塊顯示（經 DialogStackCoordinator 排隊）</summary>
    public void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info)
    {
        if (NotificationPresentation.UsesDialog(type))
        {
            PostToUi(() => _ = ShowErrorDialogSafeAsync(message, title ?? NotificationPresentation.GetDefaultTitle(type)));
            return;
        }

        PostToUi(() =>
        {
            if (MainWindow is MainWindow mw)
            {
                mw.ShowNotification(message, title, type);
            }
        });
    }

    private async Task ShowErrorDialogSafeAsync(string message, string title)
    {
        try
        {
            await ShowErrorAsync(message, title);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "顯示通知對話方塊失敗");
        }
    }

    public async Task ShowErrorAsync(string message, string title)
    {
        AudioFeedback.PlayError();
        var dialog = new NotificationDialog(this, title, message);
        await ShowContentDialogAsync(dialog);
    }

    public void CopyToClipboard(string text)
    {
        PostToUi(() =>
        {
            var package = new DataPackage();
            package.SetText(text);
            Clipboard.SetContent(package);
        });
    }

    public void ActivateMainWindow()
    {
        PostToUi(() =>
        {
            if (MainWindow is not null)
            {
                if (MainWindow.AppWindow.Presenter is OverlappedPresenter presenter &&
                    presenter.State == OverlappedPresenterState.Minimized)
                {
                    presenter.Restore();
                }
                MainWindow.Activate();
            }
        });
    }

    public void ShutdownApplication(int exitCode = 0)
    {
        Environment.ExitCode = exitCode;
        PostToUi(() =>
        {
            Application.Current?.Exit();
        });
    }

    public void RestartApplication()
    {
        string? exePath = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(exePath))
        {
            // 新行程需先取得單一實體金鑰，故啟動前釋放；啟動失敗時須取回，否則使用者可另開第二個執行個體
            App.ReleaseSingleInstanceLock();
            try
            {
                _processRunner.StartDetached(new ProcessStartSpec(
                    exePath,
                    [],
                    WorkingDirectory: Path.GetDirectoryName(exePath) ?? AppContext.BaseDirectory,
                    CreateNoWindow: false));
            }
            catch (Exception)
            {
                App.ReacquireSingleInstanceLock();
                throw;
            }
        }

        ShutdownApplication(0);
    }

    public void PostToUi(Action action, bool afterLayout = false)
    {
        ArgumentNullException.ThrowIfNull(action);
        // afterLayout：以低優先權排入佇列，確保於版面配置與算繪完成後才執行
        _dispatcherQueue.TryEnqueue(
            afterLayout ? DispatcherQueuePriority.Low : DispatcherQueuePriority.Normal,
            () => action());
    }

    public void RunOnUi(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        if (_dispatcherQueue.HasThreadAccess)
        {
            action();
        }
        else
        {
            _dispatcherQueue.TryEnqueue(() => action());
        }
    }

    public IUiTimer CreateUiTimer(TimeSpan interval, Action tick) =>
        new WinUiTimer(_dispatcherQueue, interval, tick);

    public async Task<IReadOnlyList<string>?> PickFilesAsync(string title, FileTypeChoice fileType, bool multiselect = false)
    {
        if (!_dispatcherQueue.HasThreadAccess)
        {
            return await InvokeOnUiAsync(() => PickFilesAsync(title, fileType, multiselect));
        }

        var picker = new FileOpenPicker(CurrentActiveWindow.AppWindow.Id)
        {
            Title = title,
        };
        picker.FileTypeFilter.Add(fileType.Extension);

        if (multiselect)
        {
            var files = await picker.PickMultipleFilesAsync();
            return files is { Count: > 0 } ? files.Select(static f => f.Path).ToList() : null;
        }
        else
        {
            var file = await picker.PickSingleFileAsync();
            return file is not null ? new[] { file.Path } : null;
        }
    }

    public async Task<string?> PickSaveFileAsync(string title, string fileName, FileTypeChoice fileType)
    {
        if (!_dispatcherQueue.HasThreadAccess)
        {
            return await InvokeOnUiAsync(() => PickSaveFileAsync(title, fileName, fileType));
        }

        var picker = new FileSavePicker(CurrentActiveWindow.AppWindow.Id)
        {
            Title = title,
            SuggestedFileName = fileName,
        };
        picker.FileTypeChoices[fileType.Label] = [fileType.Extension];

        var file = await picker.PickSaveFileAsync();
        return file?.Path;
    }

    public async Task<string?> PickFolderAsync(string title, string? initialDirectory = null)
    {
        if (!_dispatcherQueue.HasThreadAccess)
        {
            return await InvokeOnUiAsync(() => PickFolderAsync(title, initialDirectory));
        }

        var picker = new FolderPicker(CurrentActiveWindow.AppWindow.Id)
        {
            Title = title,
        };
        if (!string.IsNullOrWhiteSpace(initialDirectory) && Path.IsPathFullyQualified(initialDirectory))
        {
            picker.SuggestedFolder = initialDirectory;
        }
        var folder = await picker.PickSingleFolderAsync();
        return folder?.Path;
    }

    public Task<bool?> ShowManageJavaAsync(ManageJavaViewModel viewModel) =>
        ShowModalAsync(new ManageJavaDialog(viewModel), static d => d.DialogResult);

    public async Task<bool?> ShowJvmArgsAsync(JvmArgsViewModel viewModel) =>
        await ShowContentDialogAsync(new JvmArgsDialog(viewModel)) == ContentDialogResult.Primary;

    public Task<bool?> ShowServerPropertiesAsync(ServerPropertiesViewModel viewModel) =>
        ShowModalAsync(new ServerPropertiesDialog(viewModel), static d => d.DialogResult);

    public Task<bool?> ShowPlayerManagementAsync(PlayerManagementViewModel viewModel) =>
        ShowModalAsync(new PlayerManagementDialog(viewModel), static d => d.DialogResult);

    public Task<bool?> ShowRestoreBackupAsync(RestoreBackupViewModel viewModel) =>
        ShowModalAsync(new RestoreBackupDialog(viewModel), static d => d.DialogResult);

    public async Task<bool?> ShowServerMemoryAsync(ServerMemoryViewModel viewModel) =>
        await ShowContentDialogAsync(new ServerMemoryDialog(viewModel)) == ContentDialogResult.Primary;

    public async Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel) =>
        await ShowContentDialogAsync(new ImportServerDialog(viewModel)) == ContentDialogResult.Primary;

    public Task<bool?> ShowModVersionPickerAsync(ModVersionPickerViewModel viewModel) =>
        ShowModalAsync(new ModVersionPickerDialog(viewModel), static d => d.DialogResult);

    public Task<bool?> ShowModInstallQueueAsync(ObservableCollection<ModInstallQueueItem> queue) =>
        ShowModalAsync(new ModInstallQueueDialog(queue), static d => d.DialogResult);

    public async Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(IEnumerable<ModUpdateCandidateItem> items) => await ShowModalAsync(new ModUpdatesDialog(items, this), static d => d.DialogResult == true ? d.GetSelectedItems() : null);

    public async Task<ServerDeleteDecision> ShowServerDeleteConfirmationAsync(string serverName, int backupCount)
    {
        AudioFeedback.PlayWarning();
        var dialog = new ServerDeleteConfirmationDialog(serverName, backupCount);
        var result = await ShowContentDialogAsync(dialog);
        return (result is ContentDialogResult.Primary or ContentDialogResult.Secondary)
            ? dialog.Decision
            : ServerDeleteDecision.Cancel;
    }

    public async Task ShowExportModListAsync(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher launcher)
    {
        var vm = new ExportModListViewModel(serverName, rows, exporter, launcher, this);
        var dialog = new ExportModListDialog();

        // 格式對話方塊關閉後才執行匯出流程；取消儲存或匯出失敗時重新顯示格式選擇
        while (await ShowContentDialogAsync(dialog) == ContentDialogResult.Primary)
        {
            if (await vm.ExportAsync(dialog.SelectedFormat))
            {
                return;
            }
        }
    }

    public async Task<bool> ShowServerInitializationAsync(ServerInitializationViewModel viewModel)
    {
        using var dialog = new ServerInitializationDialog(viewModel);
        return await ShowModalAsync(dialog, static d => d.IsSuccess);
    }

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel)
    {
        var window = new ServerMonitorWindow(viewModel, this);
        // 圖示、標題列與內容主題已由 ServerMonitorWindow 建構時套用
        ModalWindowHost.CenterOnParent(window, MainWindow);
        var handle = new MonitorWindowHandle(window);
        window.Activate();
        return handle;
    }

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份") =>
        ShowProgressSession<ServerBackupProgressReport>(
            $"正在{actionTitle}伺服器「{serverName}」",
            actionTitle == "還原" ? "正在準備還原環境與解壓縮備份..." : "正在收集伺服器檔案...",
            report => (report.PercentCompleted, !string.IsNullOrWhiteSpace(report.CurrentFile)
                ? $"正在壓縮：{report.CurrentFile}"
                : (report.PercentCompleted >= 100 ? $"{actionTitle}壓縮完成！" : string.Empty)));

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName) =>
        ShowProgressSession<ServerImportProgressReport>(
            $"正在匯入伺服器「{serverName}」",
            "正在驗證伺服器目錄...",
            static report => (report.Percentage, report.StageText));

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName) =>
        ShowProgressSession<ServerCreationProgressReport>(
            $"正在建立伺服器「{serverName}」",
            "正在驗證伺服器名稱與目錄...",
            static report => (report.PercentCompleted, $"[{report.Phase}] {report.Message}"));

    public IOperationProgress ShowModOperationProgress(string title, string initialMessage) =>
        new ModOperationProgressHandle(OpenProgressDialog(title, initialMessage));

    /// <summary>以目前作用中視窗為擁有者開啟原生模態視窗並等待結果（統一主題、置中與視窗堆疊）</summary>
    private Task<TResult> ShowModalAsync<TWindow, TResult>(TWindow window, Func<TWindow, TResult> resultSelector)
        where TWindow : Window =>
        ModalWindowHost.ShowModalAsync(window, CurrentActiveWindow, CurrentTheme, resultSelector, PushWindow, PopWindow);

    /// <summary>開啟進度對話框；顯示失敗時記錄並關閉，避免作業完成後殘留無法關閉的視窗</summary>
    private OperationProgressDialog OpenProgressDialog(string heading, string initialMessage)
    {
        var dialog = new OperationProgressDialog(this, heading, initialMessage);
        _ = ShowProgressDialogSafeAsync(dialog);
        return dialog;
    }

    private async Task ShowProgressDialogSafeAsync(OperationProgressDialog dialog)
    {
        try
        {
            await ShowContentDialogAsync(dialog).ConfigureAwait(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "顯示進度對話框失敗");
            dialog.MarkCompleted();
        }
    }

    private ProgressSession<TReport> ShowProgressSession<TReport>(string heading, string initialMessage, Func<TReport, (int Percent, string Message)> map)
    {
        var dialog = OpenProgressDialog(heading, initialMessage);
        var progress = new Progress<TReport>(report =>
        {
            var (percent, message) = map(report);
            dialog.UpdateProgress(percent, message);
        });
        return new ProgressSession<TReport>(progress, dialog);
    }

    private sealed class WinUiTimer : IUiTimer
    {
        private readonly DispatcherQueueTimer _timer;

        public WinUiTimer(DispatcherQueue dispatcherQueue, TimeSpan interval, Action tick)
        {
            _timer = dispatcherQueue.CreateTimer();
            _timer.Interval = interval;
            _timer.IsRepeating = true;
            _timer.Tick += (_, _) => tick();
        }

        public void StartTimer() => _timer.Start();

        public void StopTimer() => _timer.Stop();
    }

    private sealed class MonitorWindowHandle : IMonitorWindow
    {
        private readonly ServerMonitorWindow _window;
        private bool _isOpen = true;

        public MonitorWindowHandle(ServerMonitorWindow window)
        {
            _window = window;
            _window.Closed += (_, _) =>
            {
                _isOpen = false;
                Closed?.Invoke();
            };
        }

        public bool IsOpen => _isOpen;

        public event Action? Closed;

        public void BringToFront() => _window.Activate();

        public void Close() => _window.Close();
    }

    private sealed partial class ProgressSession<TReport>(IProgress<TReport> progress, OperationProgressDialog dialog) : IProgressSession<TReport>
    {
        public IProgress<TReport> Progress { get; } = progress;

        public void Dispose() => dialog.Close();
    }

    private sealed partial class ModOperationProgressHandle(OperationProgressDialog dialog) : IOperationProgress
    {
        private readonly OperationProgressDialog _dialog = dialog;

        public void UpdateProgress(int current, int total, string message)
        {
            int percent = total > 0 ? (int)Math.Round((double)current / total * 100) : 0;
            _dialog.UpdateProgress(percent, message);
        }

        public void Dispose() => _dialog.Close();
    }
}
