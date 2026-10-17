using System.Collections.ObjectModel;
using System.Windows;
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
    public bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question)
    {
        var owner = GetDefaultOwner(title);
        return owner is not null
            ? MessageBox.Show(owner, message, title, MessageBoxButton.YesNo, ToImage(level)) == MessageBoxResult.Yes
            : MessageBox.Show(message, title, MessageBoxButton.YesNo, ToImage(level)) == MessageBoxResult.Yes;
    }

    public void ShowInfo(string message, string title)
    {
        var owner = GetDefaultOwner(title);
        if (owner is not null)
        {
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Information);
        }
        else
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    public void ShowMonitorInfo(string serverName, string message, string title)
    {
        Window? owner = null;
        if (Application.Current is not null)
        {
            owner = Application.Current.Windows.OfType<ServerMonitorWindow>()
                .FirstOrDefault(w => w.IsLoaded && w.IsVisible &&
                    w.DataContext is ServerMonitorViewModel vm &&
                    string.Equals(vm.ServerName, serverName, StringComparison.OrdinalIgnoreCase))
                ?? Application.Current.Windows.OfType<ServerMonitorWindow>().LastOrDefault(w => w.IsLoaded && w.IsVisible)
                ?? GetDefaultOwner(title);
        }

        if (owner is not null)
        {
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Information);
        }
        else
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    public void ShowWarning(string message, string title)
    {
        var owner = GetDefaultOwner(title);
        if (owner is not null)
        {
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        else
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    public void ShowError(string message, string title)
    {
        var owner = GetDefaultOwner(title);
        if (owner is not null)
        {
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Error);
        }
        else
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private static Window? GetDefaultOwner(string? title = null)
    {
        if (Application.Current is null)
        {
            return null;
        }

        if (title is "伺服器啟動成功" or "伺服器就緒")
        {
            var monitor = Application.Current.Windows.OfType<ServerMonitorWindow>().LastOrDefault(w => w.IsLoaded && w.IsVisible);
            if (monitor is not null)
            {
                return monitor;
            }
        }

        var active = Application.Current.Windows.OfType<Window>().FirstOrDefault(w => w.IsActive && w.IsLoaded);
        if (active is not null)
        {
            return active;
        }

        var visibleMonitor = Application.Current.Windows.OfType<ServerMonitorWindow>().LastOrDefault(w => w.IsLoaded && w.IsVisible);
        return visibleMonitor ?? Application.Current.MainWindow;
    }

    public void ShowNotificationPopup(string title, string message, NotificationLevel level) =>
        NotificationDialog.Show(null, title, message, level);

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
        Attach(new ExportModListDialog(serverName, rows, exporter, launcher, this)).ShowDialog();

    public bool ShowServerInitialization(ServerConfig config, string javaPath, IServerRuntime runtime)
    {
        using var dialog = new ServerInitializationDialog(runtime, config, javaPath);
        SetOwner(dialog);
        dialog.ShowDialog();
        return dialog.IsSuccess;
    }

    public IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel)
    {
        var window = new ServerMonitorWindow(viewModel);
        var handle = new MonitorWindowHandle(window);
        window.Show();
        return handle;
    }

    public IProgressSession<ServerBackupProgressReport> ShowServerBackupProgress(string serverName, string actionTitle = "備份")
    {
        var dialog = Attach(new ServerBackupProgressDialog(serverName, actionTitle));
        dialog.Show();
        return new ProgressSession<ServerBackupProgressReport>(dialog.Progress, dialog, dialog.MarkCompleted);
    }

    public IProgressSession<ServerImportProgressReport> ShowServerImportProgress(string serverName)
    {
        var dialog = Attach(new ServerImportProgressDialog(serverName));
        dialog.Show();
        return new ProgressSession<ServerImportProgressReport>(dialog.Progress, dialog, dialog.MarkCompleted);
    }

    public IProgressSession<ServerCreationProgressReport> ShowServerCreationProgress(string serverName)
    {
        var dialog = Attach(new ServerCreationProgressDialog(serverName));
        dialog.Show();
        return new ProgressSession<ServerCreationProgressReport>(dialog.Progress, dialog, dialog.MarkCompleted);
    }

    public IModOperationProgress ShowModOperationProgress(string title, string initialMessage)
    {
        var dialog = Attach(new ModOperationProgressDialog(title, initialMessage));
        dialog.Show();
        return new ModOperationProgressHandle(dialog);
    }

    public IOperationProgress ShowOperationProgress(string title, string initialMessage) =>
        ShowModOperationProgress(title, initialMessage);

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

    private static MessageBoxImage ToImage(UiMessageLevel level) => level switch
    {
        UiMessageLevel.Information => MessageBoxImage.Information,
        UiMessageLevel.Warning => MessageBoxImage.Warning,
        UiMessageLevel.Error => MessageBoxImage.Error,
        _ => MessageBoxImage.Question,
    };

    private static T Attach<T>(T window) where T : Window
    {
        SetOwner(window);
        return window;
    }

    private static void SetOwner(Window window)
    {
        if (Application.Current?.MainWindow is { } owner && !ReferenceEquals(owner, window))
        {
            window.Owner = owner;
        }
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
            window.Dispatcher.Invoke(action);
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

    private sealed class ModOperationProgressHandle(ModOperationProgressDialog dialog) : IModOperationProgress
    {
        public void UpdateProgress(int current, int total, string message) =>
            dialog.Dispatcher.InvokeAsync(() => dialog.UpdateProgress(current, total, message));

        public void UpdateMessage(string message) =>
            dialog.Dispatcher.InvokeAsync(() => dialog.UpdateMessage(message));

        public void Close() => RunOnUi(dialog, dialog.Close);
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
