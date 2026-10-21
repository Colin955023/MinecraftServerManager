using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Win32;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// <see cref="IUiService"/> 的 WPF 實作；所有 Window、MessageBox 與檔案對話方塊的建立都集中於此
/// </summary>
public sealed class WpfUiService : IUiService
{
    private static ImageSource? s_cachedAppIcon;

    public bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question)
    {
        var owner = GetDefaultOwner();
        return CustomConfirmDialog.Show(owner, message, title, level);
    }

    public void ShowToast(string message, string? title = null, ToastType type = ToastType.Info, int durationSeconds = 3) => ToastWindow.Instance.ShowToast(message, title, type, durationSeconds);

    public void ShowWarning(string message, string title)
    {
        var owner = GetDefaultOwner();
        NotificationDialog.Show(owner, title, message, NotificationLevel.Warning);
    }

    public void ShowError(string message, string title)
    {
        var owner = GetDefaultOwner();
        NotificationDialog.Show(owner, title, message, NotificationLevel.Error);
    }

    private static Window? GetDefaultOwner()
    {
        if (Application.Current is null)
        {
            return null;
        }

        var active = Application.Current.Windows.OfType<Window>().FirstOrDefault(w => w.IsActive && w.IsLoaded);
        if (active is not null)
        {
            return active;
        }

        var visibleMonitor = Application.Current.Windows.OfType<ServerMonitorWindow>().LastOrDefault(w => w.IsLoaded && w.IsVisible);
        return visibleMonitor ?? Application.Current.MainWindow;
    }

    public void CopyToClipboard(string text) => Clipboard.SetText(text);

    public void ActivateMainWindow() =>
        Application.Current?.Dispatcher.InvokeAsync(static () =>
        {
            var mainWindow = Application.Current?.MainWindow;
            if (mainWindow is null)
            {
                return;
            }

            if (mainWindow.WindowState == WindowState.Minimized)
            {
                mainWindow.WindowState = WindowState.Normal;
            }

            mainWindow.Activate();
            mainWindow.Focus();
        });

    public void ShutdownApplication(int exitCode = 0) => Application.Current?.Shutdown(exitCode);

    public IReadOnlyList<string>? PickFiles(string title, string filter, bool multiselect = false)
    {
        var dialog = new OpenFileDialog
        {
            Title = title,
            Filter = filter,
            Multiselect = multiselect,
        };
        return dialog.ShowDialog() == true ? dialog.FileNames : null;
    }

    public string? PickSaveFile(string title, string fileName, string filter)
    {
        var dialog = new SaveFileDialog
        {
            Title = title,
            FileName = fileName,
            Filter = filter,
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }

    public string? PickFolder(string title, string? initialDirectory = null)
    {
        var dialog = new OpenFolderDialog
        {
            Title = title,
            Multiselect = false,
        };
        if (!string.IsNullOrWhiteSpace(initialDirectory))
        {
            dialog.InitialDirectory = initialDirectory;
        }
        return dialog.ShowDialog() == true ? dialog.FolderName : null;
    }

    public void PostToUi(Action action) => Application.Current?.Dispatcher.InvokeAsync(action);

    public void RunOnUi(Action action)
    {
        var dispatcher = Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess())
        {
            action();
        }
        else
        {
            dispatcher.InvokeAsync(action);
        }
    }

    public IUiTimer CreateUiTimer(TimeSpan interval, Action tick) => new UiTimer(interval, tick);

    public bool? ShowManageJava(ManageJavaViewModel viewModel) => Attach(new ManageJavaDialog(viewModel)).ShowDialog();

    public bool? ShowJvmArgs(JvmArgsViewModel viewModel) => Attach(new JvmArgsDialog(viewModel)).ShowDialog();

    public bool? ShowServerProperties(ServerPropertiesViewModel viewModel) => Attach(new ServerPropertiesDialog(viewModel)).ShowDialog();

    public bool? ShowPlayerManagement(PlayerManagementViewModel viewModel) => Attach(new PlayerManagementDialog(viewModel)).ShowDialog();

    public bool? ShowRestoreBackup(RestoreBackupViewModel viewModel) => Attach(new RestoreBackupDialog(viewModel)).ShowDialog();

    public bool? ShowServerMemory(ServerMemoryViewModel viewModel) => Attach(new ServerMemoryDialog(viewModel)).ShowDialog();

    public bool? ShowImportServer(ImportServerViewModel viewModel) => Attach(new ImportServerDialog(viewModel)).ShowDialog();

    public bool? ShowModVersionPicker(ModVersionPickerViewModel viewModel) => Attach(new ModVersionPickerDialog(viewModel)).ShowDialog();

    public bool? ShowModInstallQueue(ObservableCollection<ModInstallQueueItem> queue) => Attach(new ModInstallQueueDialog(queue)).ShowDialog();

    public IReadOnlyList<ModUpdateCandidateItem>? ShowModUpdates(IEnumerable<ModUpdateCandidateItem> items)
    {
        var dialog = Attach(new ModUpdatesDialog(items));
        return dialog.ShowDialog() == true ? dialog.GetSelectedItems() : null;
    }

    public ServerDeleteDecision ShowServerDeleteConfirmation(string serverName, int backupCount)
    {
        var dialog = Attach(new ServerDeleteConfirmationDialog(serverName, backupCount));
        return dialog.ShowDialog() != true ? ServerDeleteDecision.Cancel : dialog.Decision;
    }

    public void ShowExportModList(string serverName, IReadOnlyList<ModListExportRow> rows, IModListExporter exporter, IExternalLauncher? launcher) =>
        Attach(new ExportModListDialog(new ExportModListViewModel(serverName, rows, exporter, launcher, this))).ShowDialog();

    public bool ShowServerInitialization(ServerConfig config, string javaPath, IServerRuntime runtime)
    {
        using var dialog = new ServerInitializationDialog(runtime, config, javaPath);
        PrepareDialog(dialog, Application.Current?.MainWindow);
        dialog.ShowDialog();
        return dialog.IsSuccess;
    }

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel)
    {
        var window = new ServerMonitorWindow(viewModel);
        PrepareDialog(window, owner: null);
        var handle = new MonitorWindowHandle(window);
        window.Show();
        return handle;
    }

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份")
    {
        var dialog = Attach(new OperationProgressDialog($"{actionTitle}伺服器中", $"正在{actionTitle}伺服器「{serverName}」", actionTitle == "還原" ? "正在準備還原環境與解壓縮備份..." : "正在收集伺服器檔案..."));
        dialog.Show();
        var progress = new Progress<ServerBackupProgressReport>(report =>
        {
            int percent = Math.Clamp(report.PercentCompleted, 0, 100);
            string msg = !string.IsNullOrWhiteSpace(report.CurrentFile)
                ? $"正在壓縮: {report.CurrentFile}"
                : (percent >= 100 ? $"{actionTitle}壓縮完成！" : string.Empty);
            dialog.UpdateProgress(percent, msg);
        });
        return new ProgressSession<ServerBackupProgressReport>(progress, dialog, dialog.MarkCompleted);
    }

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName)
    {
        var dialog = Attach(new OperationProgressDialog("匯入伺服器中", $"正在匯入伺服器「{serverName}」", "正在驗證伺服器目錄..."));
        dialog.Show();
        var progress = new Progress<ServerImportProgressReport>(report =>
        {
            int percent = Math.Clamp(report.Percentage, 0, 100);
            dialog.UpdateProgress(percent, report.StageText);
        });
        return new ProgressSession<ServerImportProgressReport>(progress, dialog, dialog.MarkCompleted);
    }

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName)
    {
        var dialog = Attach(new OperationProgressDialog("建立伺服器中", $"正在建立伺服器「{serverName}」", "正在驗證伺服器名稱與目錄..."));
        dialog.Show();
        var progress = new Progress<ServerCreationProgressReport>(report =>
        {
            int percent = Math.Clamp(report.PercentCompleted, 0, 100);
            dialog.UpdateProgress(percent, $"[{report.Phase}] {report.Message}");
        });
        return new ProgressSession<ServerCreationProgressReport>(progress, dialog, dialog.MarkCompleted);
    }

    public IOperationProgress ShowModOperationProgress(string title, string initialMessage)
    {
        var dialog = Attach(new OperationProgressDialog(title, title, initialMessage));
        dialog.Show();
        return new ModOperationProgressHandle(dialog);
    }

    private sealed class UiTimer : IUiTimer
    {
        private readonly DispatcherTimer _timer;

        public UiTimer(TimeSpan interval, Action tick)
        {
            _timer = new DispatcherTimer { Interval = interval };
            _timer.Tick += (_, _) => tick();
        }

        public void StartTimer() => _timer.Start();

        public void StopTimer() => _timer.Stop();
    }


    private static T Attach<T>(T window) where T : Window
    {
        PrepareDialog(window, GetDefaultOwner());
        return window;
    }

    private static void PrepareDialog(Window dialog, Window? owner)
    {
        if (owner is not null && !ReferenceEquals(owner, dialog))
        {
            dialog.Owner = owner;
        }

        if (dialog.Icon is null)
        {
            dialog.Icon = owner?.Icon ?? GetCachedAppIcon();
        }

        if (Application.Current?.Resources["UiScaleTransform"] is Transform scaleTransform &&
            dialog.Content is FrameworkElement rootElement)
        {
            rootElement.LayoutTransform = scaleTransform;
        }
    }

    private static ImageSource? GetCachedAppIcon()
    {
        if (s_cachedAppIcon is not null)
        {
            return s_cachedAppIcon;
        }

        try
        {
            var frame = BitmapFrame.Create(
                new Uri("pack://application:,,,/MinecraftServerManager.App;component/assets/icon.ico", UriKind.RelativeOrAbsolute));
            frame.Freeze();
            s_cachedAppIcon = frame;
        }
        catch
        {
        }

        return s_cachedAppIcon;
    }

    /// <summary>
    /// 確保在 UI 執行緒上執行；若目前不在 UI 執行緒則同步派送
    /// </summary>
    private static void RunOnUi(Window window, Action action)
    {
        if (window.Dispatcher.CheckAccess())
        {
            action();
        }
        else
        {
            window.Dispatcher.BeginInvoke(action);
        }
    }

    private sealed class ProgressSession<TReport>(IProgress<TReport> progress, Window window, Action markCompleted) : IProgressSession<TReport>
    {
        public IProgress<TReport> Progress => progress;

        public void Complete()
        {
            markCompleted();
            RunOnUi(window, window.Close);
        }
    }

    private sealed class ModOperationProgressHandle(OperationProgressDialog dialog) : IOperationProgress
    {
        public void UpdateProgress(int current, int total, string message) =>
            dialog.UpdateProgress(current, total, message);

        public void Close()
        {
            dialog.MarkCompleted();
            RunOnUi(dialog, dialog.Close);
        }
    }

    private sealed class MonitorWindowHandle : IMonitorWindow
    {
        private readonly ServerMonitorWindow _window;

        public MonitorWindowHandle(ServerMonitorWindow window)
        {
            _window = window;
            _window.Closed += (_, _) => Closed?.Invoke();
        }

        public bool IsOpen => _window.IsLoaded;

        public event Action? Closed;

        public void BringToFront()
        {
            if (_window.WindowState == WindowState.Minimized)
            {
                _window.WindowState = WindowState.Normal;
            }

            _window.Activate();
            _window.Focus();
        }
    }
}
