using System.Runtime.CompilerServices;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Windows.Storage.Pickers;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.ApplicationModel.DataTransfer;

namespace MinecraftServerManager.App.Services;

/// <summary>支援暫時隱藏以讓位給巢狀對話框的 ContentDialog</summary>
public interface INestableContentDialog
{
    public void HideForNestedDialog();
}

/// <summary>WinUI 3 介面服務：所有 WinUI 物件一律於 UI 執行緒建立與操作</summary>
public sealed partial class WinUiService : IUiService, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(WinUiService));

    private readonly DispatcherQueue _dispatcherQueue;
    private readonly IProcessRunner _processRunner;
    private readonly IAccentColorService _accentColorService;
    private readonly Lock _windowLock = new();
    // 模態視窗堆疊：最上層為目前擁有輸入的視窗
    private readonly List<Window> _modalStack = [];
    // 非模態監控視窗：只有在前景作用中時才作為對話框擁有者
    private readonly List<Window> _monitorWindows = [];
    private readonly ConditionalWeakTable<XamlRoot, DialogStackCoordinator> _coordinators = [];
    private Window? _activeMonitorWindow;
    private bool _disposed;

    public WinUiService(DispatcherQueue dispatcherQueue, IProcessRunner processRunner, IAccentColorService accentColorService)
    {
        ArgumentNullException.ThrowIfNull(dispatcherQueue);
        ArgumentNullException.ThrowIfNull(processRunner);
        ArgumentNullException.ThrowIfNull(accentColorService);

        _dispatcherQueue = dispatcherQueue;
        _processRunner = processRunner;
        _accentColorService = accentColorService;
        _accentColorService.AccentColorChanged += OnAccentColorChanged;
    }

    public Window? MainWindow { get; private set; }

    /// <summary>程式主題；變更時同步至所有已開啟視窗的內容與標題列</summary>
    public ElementTheme CurrentTheme
    {
        get;
        set
        {
            if (field == value)
            {
                return;
            }

            field = value;
            RunOnUi(() =>
            {
                foreach (Window window in SnapshotWindows())
                {
                    ApplyWindowTheme(window, value);
                }
            });
        }
    } = ElementTheme.Default;

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _accentColorService.AccentColorChanged -= OnAccentColorChanged;
    }

    /// <summary>強調色筆刷已於資源字典就地更新，此處只需同步標題列</summary>
    private void OnAccentColorChanged() => RunOnUi(() =>
    {
        foreach (Window window in SnapshotWindows())
        {
            WindowChromeService.ApplyTheme(window.AppWindow, CurrentTheme);
        }
    });

    public void RegisterMainWindow(Window mainWindow)
    {
        ArgumentNullException.ThrowIfNull(mainWindow);
        MainWindow = mainWindow;
    }

    /// <summary>於鎖內複製目前所有開啟中的視窗，供鎖外套用主題</summary>
    private List<Window> SnapshotWindows()
    {
        lock (_windowLock)
        {
            var windows = new List<Window>(_modalStack.Count + _monitorWindows.Count + 1);
            if (MainWindow is not null)
            {
                windows.Add(MainWindow);
            }

            windows.AddRange(_modalStack);
            windows.AddRange(_monitorWindows);
            return windows;
        }
    }

    private static void ApplyWindowTheme(Window window, ElementTheme theme)
    {
        if (window.AppWindow is not null && window.Content is FrameworkElement fe)
        {
            fe.RequestedTheme = theme;
            WindowChromeService.ApplyTheme(window.AppWindow, theme);
        }
    }

    /// <summary>目前擁有輸入的視窗：最上層模態視窗、前景中的監控視窗，否則為主視窗</summary>
    private Window CurrentActiveWindow
    {
        get
        {
            lock (_windowLock)
            {
                for (int i = _modalStack.Count - 1; i >= 0; i--)
                {
                    if (_modalStack[i].AppWindow is null)
                    {
                        _modalStack.RemoveAt(i);
                        continue;
                    }

                    return _modalStack[i];
                }

                if (_activeMonitorWindow?.AppWindow is not null)
                {
                    return _activeMonitorWindow;
                }
            }

            return MainWindow ?? throw new InvalidOperationException("目前無作用中的視窗。");
        }
    }

    private void PushModal(Window window)
    {
        lock (_windowLock)
        {
            _modalStack.Add(window);
        }
    }

    private void PopModal(Window window)
    {
        lock (_windowLock)
        {
            _modalStack.Remove(window);
        }
    }

    private XamlRoot GetCurrentXamlRoot()
    {
        if (CurrentActiveWindow.Content?.XamlRoot is { } root)
        {
            return root;
        }

        if (MainWindow?.Content?.XamlRoot is { } mainRoot)
        {
            return mainRoot;
        }

        throw new InvalidOperationException("無法取得作用中的 XamlRoot。");
    }

    /// <summary>於 UI 執行緒執行非同步作業；已在 UI 執行緒時直接執行</summary>
    private Task<T> RunOnUiAsync<T>(Func<Task<T>> operation)
    {
        if (_dispatcherQueue.HasThreadAccess)
        {
            return operation();
        }

        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        bool enqueued = _dispatcherQueue.TryEnqueue(async () =>
        {
            try
            {
                tcs.TrySetResult(await operation());
            }
            catch (OperationCanceledException ex)
            {
                tcs.TrySetCanceled(ex.CancellationToken);
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

        return tcs.Task;
    }

    /// <summary>於 UI 執行緒建立並排隊顯示 ContentDialog，以 <paramref name="selector"/> 取得結果</summary>
    private Task<TResult> ShowContentDialogAsync<TDialog, TResult>(Func<TDialog> factory, Func<TDialog, ContentDialogResult, TResult> selector)
        where TDialog : ContentDialog =>
        RunOnUiAsync(async () =>
        {
            TDialog dialog = factory();
            ContentDialogResult result = await ShowCreatedDialogAsync(dialog);
            return selector(dialog, result);
        });

    private Task<ContentDialogResult> ShowContentDialogAsync(Func<ContentDialog> factory) =>
        ShowContentDialogAsync(factory, static (_, result) => result);

    /// <summary>於 UI 執行緒顯示已建立的對話框；同一執行緒同時只能開一個 ContentDialog，一律共用主視窗協調器排隊</summary>
    private Task<ContentDialogResult> ShowCreatedDialogAsync(ContentDialog dialog)
    {
        XamlRoot root = GetCurrentXamlRoot();
        dialog.XamlRoot = root;
        dialog.RequestedTheme = CurrentTheme;

        var coordinator = _coordinators.GetOrCreateValue(MainWindow?.Content?.XamlRoot ?? root);
        return coordinator.ShowDialogAsync(
            () => dialog.ShowAsync().AsTask(),
            () =>
            {
                if (dialog is INestableContentDialog nestable)
                {
                    nestable.HideForNestedDialog();
                }
                else
                {
                    dialog.Hide();
                }
            });
    }

    public Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question)
    {
        AudioFeedback.Play(level);
        return ShowContentDialogAsync(
            () => new CustomConfirmDialog(message, title, level),
            static (_, result) => result == ContentDialogResult.Primary);
    }

    public Task<bool> ConfirmChoiceAsync(string message, string title, string primaryText, string closeText, UiMessageLevel level = UiMessageLevel.Question)
    {
        AudioFeedback.Play(level);
        return ShowContentDialogAsync(
            () => new CustomConfirmDialog(message, title, level, primaryText, null, closeText),
            static (_, result) => result == ContentDialogResult.Primary);
    }

    public Task<bool?> ConfirmYesNoCancelAsync(
        string message,
        string title,
        string yesText = "是",
        string noText = "否",
        string cancelText = "取消",
        UiMessageLevel level = UiMessageLevel.Question)
    {
        AudioFeedback.Play(level);
        return ShowContentDialogAsync(
            () => new CustomConfirmDialog(message, title, level, yesText, noText, cancelText),
            static (_, result) => result switch
            {
                ContentDialogResult.Primary => true,
                ContentDialogResult.Secondary => (bool?)false,
                _ => null,
            });
    }

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
        catch (OperationCanceledException)
        {
            Logger.Information("顯示通知對話框已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "顯示通知對話方塊失敗");
        }
    }

    public Task ShowErrorAsync(string message, string title)
    {
        AudioFeedback.PlayError();
        return ShowContentDialogAsync(() => new NotificationDialog(this, title, message));
    }

    public void CopyToClipboard(string text)
    {
        PostToUi(() =>
        {
            try
            {
                var package = new DataPackage();
                package.SetText(text);
                Clipboard.SetContent(package);
            }
            catch (Exception ex)
            {
                // 剪貼簿可能被其他程式鎖定
                Logger.Warning(ex, "複製到剪貼簿失敗");
                ShowNotification("剪貼簿目前無法使用，請稍後再試。", "複製失敗", NotificationType.Warning);
            }
        });
    }

    public void ActivateMainWindow()
    {
        PostToUi(() =>
        {
            if (MainWindow is not null)
            {
                BringWindowToFront(MainWindow);
            }
        });
    }

    /// <summary>將已開啟的視窗從最小化還原（如有）並帶至前景</summary>
    internal static void BringWindowToFront(Window window)
    {
        if (window.AppWindow.Presenter is OverlappedPresenter presenter &&
            presenter.State == OverlappedPresenterState.Minimized)
        {
            presenter.Restore();
        }

        window.Activate();
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
            LaunchReplacementInstance(() => _processRunner.StartDetached(new ProcessStartSpec(
                exePath,
                [],
                WorkingDirectory: Path.GetDirectoryName(exePath) ?? AppContext.BaseDirectory,
                CreateNoWindow: false)));
        }

        ShutdownApplication(0);
    }

    public void LaunchReplacementInstance(Action launch)
    {
        ArgumentNullException.ThrowIfNull(launch);

        // 新行程需先取得單一實體金鑰，故啟動前釋放；啟動失敗時取回
        App.ReleaseSingleInstanceLock();
        try
        {
            launch();
        }
        catch (Exception)
        {
            App.ReacquireSingleInstanceLock();
            throw;
        }
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

    public Task<IReadOnlyList<string>?> PickFilesAsync(string title, FileTypeChoice fileType, bool multiselect = false) =>
        RunOnUiAsync<IReadOnlyList<string>?>(async () =>
        {
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

            var file = await picker.PickSingleFileAsync();
            return file is not null ? (string[])[file.Path] : null;
        });

    public Task<string?> PickSaveFileAsync(string title, string fileName, FileTypeChoice fileType) =>
        RunOnUiAsync(async () =>
        {
            var picker = new FileSavePicker(CurrentActiveWindow.AppWindow.Id)
            {
                Title = title,
                SuggestedFileName = fileName,
            };
            picker.FileTypeChoices[fileType.Label] = [fileType.Extension];

            var file = await picker.PickSaveFileAsync();
            return file?.Path;
        });

    public Task<string?> PickFolderAsync(string title, string? initialDirectory = null) =>
        RunOnUiAsync(async () =>
        {
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
        });

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        var handle = new MonitorWindowHandle(this);
        RunOnUi(() => handle.Attach(CreateMonitorWindow(viewModel)));
        return handle;
    }

    private ServerMonitorWindow CreateMonitorWindow(ServerMonitorViewModel viewModel)
    {
        var window = new ServerMonitorWindow(viewModel, this, CurrentTheme);
        ModalWindowHost.CenterOnParent(window, MainWindow);
        lock (_windowLock)
        {
            _monitorWindows.Add(window);
        }

        // 只有使用者正在操作監控視窗時，由它開出的對話框與選取器才以它為父視窗
        window.Activated += (_, args) =>
        {
            lock (_windowLock)
            {
                if (args.WindowActivationState != WindowActivationState.Deactivated)
                {
                    _activeMonitorWindow = window;
                }
                else if (ReferenceEquals(_activeMonitorWindow, window))
                {
                    _activeMonitorWindow = null;
                }
            }
        };
        window.Closed += (_, _) =>
        {
            lock (_windowLock)
            {
                _monitorWindows.Remove(window);
                if (ReferenceEquals(_activeMonitorWindow, window))
                {
                    _activeMonitorWindow = null;
                }
            }
        };
        window.Activate();
        return window;
    }

    /// <summary>以目前作用中視窗為擁有者，於 UI 執行緒建立並開啟原生模態視窗後回傳宿主記錄之 DialogResult</summary>
    private Task<bool?> ShowModalAsync<TWindow>(Func<TWindow> factory)
        where TWindow : Window =>
        ShowModalAsync(factory, ModalWindowHost.GetDialogResult);

    /// <summary>於 UI 執行緒建立並排隊顯示 ContentDialog，回傳是否按下主按鈕</summary>
    private Task<bool?> ShowContentBoolDialogAsync<TDialog>(Func<TDialog> factory)
        where TDialog : ContentDialog =>
        ShowContentDialogAsync(factory, static (_, result) => (bool?)(result == ContentDialogResult.Primary));

    /// <summary>以目前作用中視窗為擁有者，於 UI 執行緒建立並開啟原生模態視窗後等待結果（統一主題、置中與視窗堆疊）</summary>
    private Task<TResult> ShowModalAsync<TWindow, TResult>(Func<TWindow> factory, Func<TWindow, TResult> resultSelector)
        where TWindow : Window =>
        RunOnUiAsync(() => ModalWindowHost.ShowModalAsync(factory(), CurrentActiveWindow, CurrentTheme, resultSelector, PushModal, PopModal));
}
