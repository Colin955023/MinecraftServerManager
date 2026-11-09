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
using MinecraftServerManager.Domain.Servers;
using Windows.ApplicationModel.DataTransfer;
using Microsoft.Windows.Storage.Pickers;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// <see cref="IUiService"/> 的 WinUI 3 原生實作。
/// 管理 ContentDialog 佇列（<see cref="DialogStackCoordinator"/>）、模態視窗宿主（<see cref="ModalWindowHost"/>）、
/// 檔案與資料夾選取器（透過 AppWindow.Id 綁定視窗）、UI 執行緒派送與計時器。
/// </summary>
public sealed class WinUiService : IUiService
{
    private static WinUiService? s_instance;
    public static WinUiService Instance => s_instance ?? throw new InvalidOperationException("WinUiService 尚未初始化。");

    private readonly DispatcherQueue _dispatcherQueue;
    private readonly Stack<Window> _windowStack = new();
    private readonly Lock _windowLock = new();
    private readonly ConditionalWeakTable<XamlRoot, DialogStackCoordinator> _coordinators = [];

    public Window? MainWindow { get; private set; }
    public ElementTheme CurrentTheme { get; set; } = ElementTheme.Default;

    public WinUiService(DispatcherQueue dispatcherQueue)
    {
        _dispatcherQueue = dispatcherQueue ?? throw new ArgumentNullException(nameof(dispatcherQueue));
        s_instance = this;
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
                _windowStack.Push(mainWindow);
            }
        }
    }

    public Window CurrentActiveWindow
    {
        get
        {
            lock (_windowLock)
            {
                while (_windowStack.Count > 0)
                {
                    var top = _windowStack.Peek();
                    if (top.AppWindow is null)
                    {
                        _windowStack.Pop();
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
            _windowStack.Push(window);
        }
    }

    public void PopWindow(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        lock (_windowLock)
        {
            if (_windowStack.Count > 0 && ReferenceEquals(_windowStack.Peek(), window))
            {
                _windowStack.Pop();
            }
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

    /// <summary>
    /// 將非同步 UI 作業派送至 UI 執行緒執行並等待結果（例外與取消皆原樣傳回呼叫端）
    /// </summary>
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

    public void ShowToast(string message, string? title = null, ToastType type = ToastType.Info, int durationSeconds = 3)
    {
        PostToUi(() =>
        {
            if (MainWindow is MainWindow mw)
            {
                mw.ShowToast(message, title, type, durationSeconds);
            }
        });
    }

    public async Task ShowWarningAsync(string message, string title)
    {
        AudioFeedback.PlayWarning();
        var dialog = new NotificationDialog(this, title, message, NotificationLevel.Warning);
        await ShowContentDialogAsync(dialog);
    }

    public async Task ShowErrorAsync(string message, string title)
    {
        AudioFeedback.PlayError();
        var dialog = new NotificationDialog(this, title, message, NotificationLevel.Error);
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
        if (!string.IsNullOrWhiteSpace(exePath) && App.CompositionRoot?.ProcessRunner is { } runner)
        {
            App.ReleaseSingleInstanceLock();
            runner.StartDetached(new ProcessStartSpec(
                exePath,
                [],
                WorkingDirectory: Path.GetDirectoryName(exePath) ?? AppContext.BaseDirectory,
                CreateNoWindow: false));
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

    public async Task<IReadOnlyList<string>?> PickFilesAsync(string title, string filter, bool multiselect = false)
    {
        if (!_dispatcherQueue.HasThreadAccess)
        {
            return await InvokeOnUiAsync(() => PickFilesAsync(title, filter, multiselect));
        }

        var picker = new FileOpenPicker(CurrentActiveWindow.AppWindow.Id)
        {
            Title = title,
        };
        PopulateFileTypeFilter(filter, picker.FileTypeFilter);

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

    public async Task<string?> PickSaveFileAsync(string title, string fileName, string filter)
    {
        if (!_dispatcherQueue.HasThreadAccess)
        {
            return await InvokeOnUiAsync(() => PickSaveFileAsync(title, fileName, filter));
        }

        var picker = new FileSavePicker(CurrentActiveWindow.AppWindow.Id)
        {
            Title = title,
            SuggestedFileName = fileName,
        };
        PopulateFileTypeChoices(filter, picker.FileTypeChoices);

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

    public async Task<bool?> ShowManageJavaAsync(ManageJavaViewModel viewModel)
    {
        var dialog = new ManageJavaDialog(viewModel);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult,
            PushWindow,
            PopWindow);
    }

    public async Task<bool?> ShowJvmArgsAsync(JvmArgsViewModel viewModel)
    {
        var dialog = new JvmArgsDialog(viewModel);
        var result = await ShowContentDialogAsync(dialog);
        return result == ContentDialogResult.Primary;
    }

    public async Task<bool?> ShowServerPropertiesAsync(ServerPropertiesViewModel viewModel)
    {
        var dialog = new ServerPropertiesDialog(viewModel);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult,
            PushWindow,
            PopWindow);
    }

    public async Task<bool?> ShowPlayerManagementAsync(PlayerManagementViewModel viewModel)
    {
        var dialog = new PlayerManagementDialog(viewModel);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult,
            PushWindow,
            PopWindow);
    }

    public async Task<bool?> ShowRestoreBackupAsync(RestoreBackupViewModel viewModel)
    {
        var dialog = new RestoreBackupDialog(viewModel);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult,
            PushWindow,
            PopWindow);
    }

    public async Task<bool?> ShowServerMemoryAsync(ServerMemoryViewModel viewModel)
    {
        var dialog = new ServerMemoryDialog(viewModel);
        var result = await ShowContentDialogAsync(dialog);
        return result == ContentDialogResult.Primary;
    }

    public async Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel)
    {
        var dialog = new ImportServerDialog(viewModel);
        var result = await ShowContentDialogAsync(dialog);
        return result == ContentDialogResult.Primary;
    }

    public async Task<bool?> ShowModVersionPickerAsync(ModVersionPickerViewModel viewModel)
    {
        var dialog = new ModVersionPickerDialog(viewModel);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult,
            PushWindow,
            PopWindow);
    }

    public async Task<bool?> ShowModInstallQueueAsync(ObservableCollection<ModInstallQueueItem> queue)
    {
        var dialog = new ModInstallQueueDialog(queue);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult,
            PushWindow,
            PopWindow);
    }

    public async Task<IReadOnlyList<ModUpdateCandidateItem>?> ShowModUpdatesAsync(IEnumerable<ModUpdateCandidateItem> items)
    {
        var dialog = new ModUpdatesDialog(items, this);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.DialogResult == true ? d.GetSelectedItems() : null,
            PushWindow,
            PopWindow);
    }

    public async Task<ServerDeleteDecision> ShowServerDeleteConfirmationAsync(string serverName, int backupCount)
    {
        AudioFeedback.PlayWarning();
        var dialog = new ServerDeleteConfirmationDialog(serverName, backupCount);
        var result = await ShowContentDialogAsync(dialog);
        return (result is ContentDialogResult.Primary or ContentDialogResult.Secondary)
            ? dialog.Decision
            : ServerDeleteDecision.Cancel;
    }

    public async Task ShowExportModListAsync(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher? launcher)
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

    public async Task<bool> ShowServerInitializationAsync(ServerConfig config, string javaPath, IServerRuntime runtime)
    {
        using var dialog = new ServerInitializationDialog(this, runtime, config, javaPath);
        return await ModalWindowHost.ShowModalAsync(
            dialog,
            CurrentActiveWindow,
            CurrentTheme,
            d => d.IsSuccess,
            PushWindow,
            PopWindow);
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

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份")
    {
        var dialog = new OperationProgressDialog(this, $"{actionTitle}伺服器中", $"正在{actionTitle}伺服器「{serverName}」", actionTitle == "還原" ? "正在準備還原環境與解壓縮備份..." : "正在收集伺服器檔案...");
        _ = ShowContentDialogAsync(dialog);
        var progress = new Progress<ServerBackupProgressReport>(report =>
        {
            int percent = Math.Clamp(report.PercentCompleted, 0, 100);
            string msg = !string.IsNullOrWhiteSpace(report.CurrentFile)
                ? $"正在壓縮：{report.CurrentFile}"
                : (percent >= 100 ? $"{actionTitle}壓縮完成！" : string.Empty);
            dialog.UpdateProgress(percent, msg);
        });
        return new ProgressSession<ServerBackupProgressReport>(progress, dialog, dialog.MarkCompleted);
    }

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName)
    {
        var dialog = new OperationProgressDialog(this, "匯入伺服器中", $"正在匯入伺服器「{serverName}」", "正在驗證伺服器目錄...");
        _ = ShowContentDialogAsync(dialog);
        var progress = new Progress<ServerImportProgressReport>(report =>
        {
            int percent = Math.Clamp(report.Percentage, 0, 100);
            dialog.UpdateProgress(percent, report.StageText);
        });
        return new ProgressSession<ServerImportProgressReport>(progress, dialog, dialog.MarkCompleted);
    }

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName)
    {
        var dialog = new OperationProgressDialog(this, "建立伺服器中", $"正在建立伺服器「{serverName}」", "正在驗證伺服器名稱與目錄...");
        _ = ShowContentDialogAsync(dialog);
        var progress = new Progress<ServerCreationProgressReport>(report =>
        {
            int percent = Math.Clamp(report.PercentCompleted, 0, 100);
            dialog.UpdateProgress(percent, $"[{report.Phase}] {report.Message}");
        });
        return new ProgressSession<ServerCreationProgressReport>(progress, dialog, dialog.MarkCompleted);
    }

    public IOperationProgress ShowModOperationProgress(string title, string initialMessage)
    {
        var dialog = new OperationProgressDialog(this, title, title, initialMessage);
        _ = ShowContentDialogAsync(dialog);
        return new ModOperationProgressHandle(dialog);
    }

    private static void PopulateFileTypeFilter(string filter, IList<string> filterList)
    {
        filterList.Clear();
        ReadOnlySpan<char> filterSpan = filter.AsSpan();
        int partIndex = 0;

        foreach (Range partRange in filterSpan.Split('|'))
        {
            if ((partIndex++ & 1) == 0)
            {
                continue;
            }

            ReadOnlySpan<char> patternSpan = filterSpan[partRange];
            foreach (Range extRange in patternSpan.Split(';'))
            {
                ReadOnlySpan<char> trimmed = patternSpan[extRange].Trim();
                if (trimmed is "*.*" or "*")
                {
                    if (!filterList.Contains("*"))
                    {
                        filterList.Add("*");
                    }
                }
                else if (trimmed.StartsWith("*.", StringComparison.Ordinal))
                {
                    string ext = trimmed[1..].ToString();
                    if (!filterList.Contains(ext))
                    {
                        filterList.Add(ext);
                    }
                }
                else if (trimmed.StartsWith('.'))
                {
                    string ext = trimmed.ToString();
                    if (!filterList.Contains(ext))
                    {
                        filterList.Add(ext);
                    }
                }
            }
        }

        if (filterList.Count == 0)
        {
            filterList.Add("*");
        }
    }

    private static void PopulateFileTypeChoices(string filter, IDictionary<string, IList<string>> choices)
    {
        choices.Clear();
        ReadOnlySpan<char> filterSpan = filter.AsSpan();
        var enumerator = filterSpan.Split('|');

        while (enumerator.MoveNext())
        {
            ReadOnlySpan<char> labelSpan = filterSpan[enumerator.Current].Trim();
            if (!enumerator.MoveNext())
            {
                break;
            }

            ReadOnlySpan<char> patternSpan = filterSpan[enumerator.Current].Trim();
            var list = new List<string>();
            foreach (Range extRange in patternSpan.Split(';'))
            {
                ReadOnlySpan<char> trimmed = patternSpan[extRange].Trim();
                if (trimmed.StartsWith("*.", StringComparison.Ordinal))
                {
                    list.Add(trimmed[1..].ToString());
                }
                else if (trimmed.StartsWith('.'))
                {
                    list.Add(trimmed.ToString());
                }
            }

            if (list.Count > 0)
            {
                choices[labelSpan.ToString()] = list;
            }
        }

        if (choices.Count == 0)
        {
            choices["所有檔案"] = ["."];
        }
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
    }

    private sealed class ProgressSession<TReport>(IProgress<TReport> progress, OperationProgressDialog dialog, Action onComplete) : IProgressSession<TReport>
    {
        public IProgress<TReport> Progress { get; } = progress;
        private readonly OperationProgressDialog _dialog = dialog;
        private readonly Action _onComplete = onComplete;

        public void Complete()
        {
            _onComplete();
            _dialog.Close();
        }
    }

    private sealed class ModOperationProgressHandle(OperationProgressDialog dialog) : IOperationProgress
    {
        private readonly OperationProgressDialog _dialog = dialog;

        public void UpdateProgress(int current, int total, string message)
        {
            int percent = total > 0 ? (int)Math.Round((double)current / total * 100) : 0;
            _dialog.UpdateProgress(percent, message);
        }

        public void Close() => _dialog.Close();
    }
}
