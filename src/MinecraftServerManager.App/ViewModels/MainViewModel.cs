using MinecraftServerManager.App.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>主視窗 ViewModel</summary>
public sealed partial class MainViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MainViewModel));
    private readonly IUiService _ui;
    private readonly SettingsManager _settingsManager;
    private readonly PageViewModelFactory _pageViewModelFactory;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IRunningServerRegistry _runningServerRegistry;
    private readonly Dictionary<string, PageViewModel> _pages = new(StringComparer.OrdinalIgnoreCase);
    private WindowMetrics? _windowMetrics;
    private readonly Dictionary<string, Func<PageViewModel>> _pageFactories = new(StringComparer.OrdinalIgnoreCase);

    [ObservableProperty]
    public partial PageViewModel CurrentPage { get; set; }

    private readonly IExternalLauncher _launcher;
    private readonly IUpdateCheckerService _updateChecker;

    [ObservableProperty]
    public partial string ThemeMode { get; set; } = "system";

    public event Action? ResetWindowSizeRequested;

    /// <summary>主題模式變更事件，通知 MainWindow 切換 WinUI 3 原生 ElementTheme</summary>
    public event Action<string>? ThemeModeChanged;

    /// <summary>偵測到新版本時觸發，由視窗負責詢問使用者</summary>
    public event Action<UpdateCheckResult>? UpdateAvailable;

    public MainViewModel(
        IUiService uiService,
        SettingsManager settingsManager,
        IUpdateCheckerService updateChecker,
        IExternalLauncher launcher,
        ILocalFileSystem fileSystem,
        IRunningServerRegistry runningServerRegistry,
        PageViewModelFactory pages)
    {
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(updateChecker);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(runningServerRegistry);
        ArgumentNullException.ThrowIfNull(pages);

        _ui = uiService;
        _settingsManager = settingsManager;
        _launcher = launcher;
        _fileSystem = fileSystem;
        _updateChecker = updateChecker;
        _runningServerRegistry = runningServerRegistry;
        _pageViewModelFactory = pages;

        var createVm = pages.CreateCreatePage((pageKey, serverName) =>
        {
            if (string.IsNullOrWhiteSpace(serverName))
            {
                Navigate(pageKey);
            }
            else
            {
                NavigateAndSelectServer(pageKey, serverName);
            }
        });

        _pages["create"] = createVm;
        _pageFactories["manage"] = () => pages.CreateManagePage(Navigate);
        _pageFactories["mods"] = pages.CreateModsPage;

        _pageFactories["about_preferences"] = () =>
        {
            var about = pages.CreateAboutPage(SetThemeMode, () => ResetWindowSizeRequested?.Invoke());
            if (_windowMetrics is { } metrics)
            {
                about.UpdateWindowMetrics(metrics);
            }

            return about;
        };

        CurrentPage = createVm;
        ApplyInitialTheme();
    }

    public SettingsManager Settings => _settingsManager;

    /// <summary>記錄主視窗最新尺寸並同步至「關於與設定」頁（頁面尚未建立時於建立時套用）</summary>
    public void UpdateWindowMetrics(WindowMetrics metrics)
    {
        _windowMetrics = metrics;
        if (_pages.TryGetValue("about_preferences", out var page) && page is AboutPreferencesViewModel about)
        {
            about.UpdateWindowMetrics(metrics);
        }
    }

    private PageViewModel? GetOrCreatePage(string pageKey)
    {
        if (string.IsNullOrWhiteSpace(pageKey))
        {
            return null;
        }

        if (_pages.TryGetValue(pageKey, out var existing))
        {
            return existing;
        }

        if (_pageFactories.TryGetValue(pageKey, out var factory))
        {
            var created = factory();
            _pages[pageKey] = created;
            return created;
        }

        return null;
    }

    /// <summary>啟動時偵測上次程式未正常結束所遺留的伺服器行程，詢問使用者是否強制終止</summary>
    public async Task CheckOrphanedServersOnStartupAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var orphans = await _runningServerRegistry.FindOrphansAsync(cancellationToken).ConfigureAwait(true);
            if (orphans.Count == 0)
            {
                return;
            }

            string list = string.Join("\n", orphans.Select(static o => $"• {o.ServerName}（PID {o.Pid}）"));
            bool terminate = await _ui.ConfirmChoiceAsync(
                $"偵測到上次程式未正常結束時遺留的伺服器行程，仍在背景執行且無法從本程式控制：\n{list}\n\n強制終止可能導致尚未寫入的世界資料遺失；若暫不處理，這些伺服器在行程結束前無法再次啟動。",
                "偵測到遺留的伺服器行程",
                primaryText: "強制終止",
                closeText: "暫不處理",
                UiMessageLevel.Warning).ConfigureAwait(true);
            if (!terminate)
            {
                return;
            }

            var failed = new List<TrackedServerProcess>();
            foreach (var orphan in orphans)
            {
                if (!await _runningServerRegistry.TerminateAsync(orphan, cancellationToken).ConfigureAwait(true))
                {
                    failed.Add(orphan);
                }
            }

            if (failed.Count == 0)
            {
                _ui.Notify("已終止遺留的伺服器行程", NotificationType.Success);
            }
            else
            {
                string failedList = string.Join("\n", failed.Select(static o => $"• {o.ServerName}（PID {o.Pid}）"));
                await _ui.ShowErrorAsync($"下列伺服器行程無法終止，請至工作管理員手動結束：\n{failedList}", "終止遺留行程失敗").ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("啟動檢查遺留伺服器行程操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "啟動檢查遺留伺服器行程失敗");
        }
    }

    /// <summary>啟動時依設定檢查更新，有新版本時觸發 <see cref="UpdateAvailable"/></summary>
    public async Task CheckForUpdateOnStartupAsync(CancellationToken cancellationToken = default)
    {
        if (!_settingsManager.IsAutoUpdateEnabled())
        {
            return;
        }

        try
        {
            UpdateCheckResult result = await _updateChecker.CheckForUpdateAsync(cancellationToken).ConfigureAwait(true);
            if (result.HasUpdate)
            {
                UpdateAvailable?.Invoke(result);
                if (GetOrCreatePage("about_preferences") is AboutPreferencesViewModel aboutPreferences)
                {
                    await aboutPreferences.HandleUpdateResultAsync(result, cancellationToken).ConfigureAwait(true);
                }
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("啟動自動檢查更新操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "啟動自動檢查更新失敗");
        }
    }

    public void Navigate(string pageKey)
    {
        switch (ShowPage(pageKey))
        {
            case ManageServerViewModel manageVm:
                _ = RunSafeAsync(manageVm.List.RefreshServers, "重新整理伺服器清單", Logger);
                break;
            case ModsViewModel modsVm:
                _ = RunSafeAsync(modsVm.RefreshServersAsync, "重新整理模組頁面伺服器清單", Logger);
                break;
        }
    }

    /// <summary>切換頁面並於伺服器管理頁選取指定伺服器；重新整理僅執行一次（不與 <see cref="Navigate"/> 的重新整理重複）</summary>
    private void NavigateAndSelectServer(string pageKey, string serverName)
    {
        if (ShowPage(pageKey) is ManageServerViewModel manageVm)
        {
            _ = RunSafeAsync(() => manageVm.List.RefreshAndSelectServerAsync(serverName), "重新整理並選取伺服器", Logger);
        }
    }

    /// <summary>啟用主視窗並切換目前頁面；找不到頁面時通知使用者並回傳 null</summary>
    private PageViewModel? ShowPage(string pageKey)
    {
        if (string.IsNullOrWhiteSpace(pageKey))
        {
            return null;
        }

        _ui.ActivateMainWindow();

        var targetPage = GetOrCreatePage(pageKey);
        if (targetPage is null)
        {
            ShowNotification($"找不到頁面：{pageKey}", NotificationType.Error);
            return null;
        }

        CurrentPage = targetPage;
        return targetPage;
    }

    [RelayCommand]
    public async Task ImportServerAsync()
    {
        var vm = _pageViewModelFactory.CreateImportServerDialog();
        if (await _ui.ShowImportServerAsync(vm).ConfigureAwait(true) == true)
        {
            bool success = true;
            if (!string.IsNullOrWhiteSpace(vm.SourcePath) && !string.IsNullOrWhiteSpace(vm.ServerName))
            {
                success = await vm.ExecuteImportAsync().ConfigureAwait(true);
            }

            if (success)
            {
                ShowNotification("伺服器匯入成功！已更新至伺服器管理清單", NotificationType.Success);
                if (string.IsNullOrWhiteSpace(vm.ImportedServerName))
                {
                    Navigate("manage");
                }
                else
                {
                    NavigateAndSelectServer("manage", vm.ImportedServerName);
                }
            }
        }
    }

    [RelayCommand]
    public Task OpenServersFolder()
    {
        string path = _settingsManager.GetServersRoot();
        if (string.IsNullOrWhiteSpace(path))
        {
            ShowNotification("尚未設定伺服器資料夾", NotificationType.Warning);
            return Task.CompletedTask;
        }

        try
        {
            _fileSystem.CreateDirectory(path);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "建立伺服器資料夾失敗");
            ShowNotification($"無法建立伺服器資料夾：{ex.Message}", NotificationType.Error);
            return Task.CompletedTask;
        }

        if (!_launcher.OpenFolder(path))
        {
            ShowNotification($"無法開啟資料夾：{path}", NotificationType.Warning);
        }

        return Task.CompletedTask;
    }

    public void ShowNotification(string message, NotificationType type = NotificationType.Info) => _ui.Notify(message, type);

    public void SetThemeMode(string mode)
    {
        ThemeMode = mode;
        _settingsManager.SetThemeMode(mode);
        ThemeModeChanged?.Invoke(mode);
    }

    private void ApplyInitialTheme()
    {
        string themeMode = _settingsManager.GetThemeMode();
        SetThemeMode(themeMode);
    }

    public void DisposePages()
    {
        foreach (var page in _pages.Values)
        {
            if (page is IDisposable d)
            {
                d.Dispose();
            }
        }
    }
}
