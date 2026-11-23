using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>主視窗 ViewModel</summary>
public sealed partial class MainViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MainViewModel));
    private readonly IUiService _ui;
    private readonly ISettingsManager _settingsManager;
    private readonly IExternalLauncher _launcher;
    private readonly PageViewModelFactory _pageViewModelFactory;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IRunningServerRegistry _runningServerRegistry;
    private readonly Dictionary<string, PageViewModel> _pages = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Func<PageViewModel>> _pageFactories = new(StringComparer.OrdinalIgnoreCase);
    private WindowMetrics? _windowMetrics;

    public MainViewModel(
        IUiService uiService,
        ISettingsManager settingsManager,
        IExternalLauncher launcher,
        ILocalFileSystem fileSystem,
        IRunningServerRegistry runningServerRegistry,
        PageViewModelFactory pages)
    {
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(runningServerRegistry);
        ArgumentNullException.ThrowIfNull(pages);

        _ui = uiService;
        _settingsManager = settingsManager;
        _launcher = launcher;
        _fileSystem = fileSystem;
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

        _pages[PageKeys.Create] = createVm;
        _pageFactories[PageKeys.Manage] = () => pages.CreateManagePage(Navigate);
        _pageFactories[PageKeys.Mods] = pages.CreateModsPage;

        _pageFactories[PageKeys.AboutPreferences] = () =>
        {
            var about = pages.CreateAboutPage(ApplyThemeMode, () => ResetWindowSizeRequested?.Invoke());
            if (_windowMetrics is { } metrics)
            {
                about.UpdateWindowMetrics(metrics);
            }

            return about;
        };

        CurrentPage = createVm;
        ApplyInitialTheme();
    }

    public event Action? ResetWindowSizeRequested;

    public event Action<string>? ThemeModeChanged;

    [ObservableProperty]
    public partial PageViewModel CurrentPage { get; set; }

    [ObservableProperty]
    public partial string ThemeMode { get; set; } = "system";


    /// <summary>記錄主視窗最新尺寸並同步至「關於與設定」頁（頁面尚未建立時於建立時套用）</summary>
    public void UpdateWindowMetrics(WindowMetrics metrics)
    {
        _windowMetrics = metrics;
        if (_pages.TryGetValue(PageKeys.AboutPreferences, out var page) && page is AboutPreferencesViewModel about)
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
            var orphans = await _runningServerRegistry.FindOrphansAsync(cancellationToken);
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
                UiMessageLevel.Warning);
            if (!terminate)
            {
                return;
            }

            var failed = new List<TrackedServerProcess>();
            foreach (var orphan in orphans)
            {
                if (!await _runningServerRegistry.TerminateAsync(orphan, cancellationToken))
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
                await _ui.ShowErrorAsync($"下列伺服器行程無法終止，請至工作管理員手動結束：\n{failedList}", "終止遺留行程失敗");
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            Logger.Information("啟動檢查遺留伺服器行程操作已取消");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "啟動檢查遺留伺服器行程失敗");
        }
    }

    /// <summary>啟動時自動檢查更新（由「關於與設定」頁處理詢問與套用）</summary>
    public Task CheckForUpdateOnStartupAsync(CancellationToken cancellationToken = default) =>
        GetOrCreatePage(PageKeys.AboutPreferences) is AboutPreferencesViewModel aboutPreferences
            ? aboutPreferences.CheckForUpdateOnStartupAsync(cancellationToken)
            : Task.CompletedTask;

    public void Navigate(string pageKey)
    {
        switch (ShowPage(pageKey))
        {
            case ManageServerViewModel manageVm:
                _ = RunSafeAsync(manageVm.List.RefreshServersAsync, "重新整理伺服器清單", Logger);
                break;
            case ModsViewModel modsVm:
                _ = RunSafeAsync(modsVm.RefreshServersAsync, "重新整理模組頁面伺服器清單", Logger);
                break;
        }
    }

    /// <summary>切換頁面並於管理頁選取指定伺服器</summary>
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
            _ui.Notify($"找不到頁面：{pageKey}", NotificationType.Error);
            return null;
        }

        CurrentPage = targetPage;
        return targetPage;
    }

    [RelayCommand]
    public async Task ImportServerAsync()
    {
        var vm = _pageViewModelFactory.CreateImportServerDialog();
        // 未完成匯入（驗證失敗、取消或錯誤）時由 ExecuteImportAsync 自行提示，不得誤報成功
        if (await _ui.ShowImportServerAsync(vm) != true
            || !await vm.ExecuteImportAsync()
            || vm.ImportedServerName is not { } importedName)
        {
            return;
        }

        _ui.Notify("伺服器匯入成功！已更新至伺服器管理清單", NotificationType.Success);
        NavigateAndSelectServer(PageKeys.Manage, importedName);
    }

    [RelayCommand]
    public async Task OpenServersFolderAsync()
    {
        string path = _settingsManager.GetServersRoot();
        if (string.IsNullOrWhiteSpace(path))
        {
            _ui.Notify("尚未設定伺服器資料夾", NotificationType.Warning);
            return;
        }

        try
        {
            await _fileSystem.CreateDirectoryAsync(path);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "建立伺服器資料夾失敗");
            _ui.Notify($"無法建立伺服器資料夾：{ex.Message}", NotificationType.Error);
            return;
        }

        _ui.OpenFolderOrWarn(_launcher, path);
    }

    /// <summary>套用主題（不寫入設定）</summary>
    public void ApplyThemeMode(string mode)
    {
        ThemeMode = mode;
        ThemeModeChanged?.Invoke(mode);
    }

    private void ApplyInitialTheme() => ApplyThemeMode(_settingsManager.GetThemeMode());

    /// <summary>寫入尚未儲存的偏好設定後處置全部頁面</summary>
    public async Task DisposePagesAsync()
    {
        if (_pages.TryGetValue(PageKeys.AboutPreferences, out var aboutPage) && aboutPage is AboutPreferencesViewModel about)
        {
            await about.FlushPendingSaveAsync();
        }

        foreach (var page in _pages.Values)
        {
            if (page is IDisposable d)
            {
                d.Dispose();
            }
        }

        _pages.Clear();
    }
}
