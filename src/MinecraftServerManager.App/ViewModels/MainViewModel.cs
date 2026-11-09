using MinecraftServerManager.App.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 主視窗 ViewModel
/// </summary>
public sealed partial class MainViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MainViewModel));
    private readonly IUiService _ui;
    private readonly SettingsManager _settingsManager;
    private readonly IServerManager _serverManager;
    private readonly ILocalFileSystem _fileSystem;
    private readonly Dictionary<string, PageViewModel> _pages = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Func<PageViewModel>> _pageFactories = new(StringComparer.OrdinalIgnoreCase);

    [ObservableProperty]
    public partial PageViewModel CurrentPage { get; set; }

    private readonly IExternalLauncher _launcher;
    private readonly IUpdateCheckerService _updateChecker;

    [ObservableProperty]
    public partial string ThemeMode { get; set; } = "system";

    public event Action? ResetWindowSizeRequested;

    /// <summary>
    /// 主題模式變更事件，通知 MainWindow 切換 WinUI 3 原生 ElementTheme
    /// </summary>
    public event Action<string>? ThemeModeChanged;

    /// <summary>
    /// 偵測到新版本時觸發，由視窗負責詢問使用者
    /// </summary>
    public event Action<UpdateCheckResult>? UpdateAvailable;

    public MainViewModel(MainViewModelDependencies dependencies)
    {
        ArgumentNullException.ThrowIfNull(dependencies);

        _ui = dependencies.UiService;
        _settingsManager = dependencies.SettingsManager;
        _serverManager = dependencies.ServerManager;
        _launcher = dependencies.Launcher;
        _fileSystem = dependencies.FileSystem;
        _updateChecker = dependencies.UpdateChecker;

        var createVm = new CreateServerViewModel(
            dependencies.FileSystem,
            _ui,
            dependencies.JavaDetector,
            dependencies.ServerManager,
            dependencies.LoaderCatalog,
            systemMemoryMb: Core.Utilities.MemoryUtils.GetTotalSystemMemoryMb(),
            launcher: dependencies.Launcher,
            navigateCallback: (pageKey, serverName) =>
            {
                Navigate(pageKey);
                if (!string.IsNullOrWhiteSpace(serverName)
                    && GetOrCreatePage("manage") is ManageServerViewModel manageVm)
                {
                    _ = RunSafeAsync(() => manageVm.List.RefreshAndSelectServerAsync(serverName), "重新整理並選取伺服器", Logger);
                }
            },
            javaRequirementService: dependencies.JavaRequirementService,
            javaInstaller: dependencies.JavaInstaller,
            serverRuntime: dependencies.ServerRuntime,
            launchPlanner: dependencies.LaunchPlanner);

        _pages["create"] = createVm;
        _pageFactories["manage"] = () => new ManageServerViewModel(dependencies, _ui, Navigate);

        _pageFactories["mods"] = () => new ModsViewModel(
            dependencies.DependencyPlanner,
            dependencies.ModListExporter,
            dependencies.ModFileService,
            _ui,
            dependencies.ServerManager,
            dependencies.ModManager,
            dependencies.ModrinthClient,
            dependencies.Launcher);

        _pageFactories["about_preferences"] = () => new AboutPreferencesViewModel(
            _ui,
            dependencies.SettingsManager,
            dependencies.UpdateChecker,
            SetThemeMode,
            () => ResetWindowSizeRequested?.Invoke(),
            dependencies.Launcher,
            dependencies.AppUpdateService);

        CurrentPage = createVm;
        ApplyInitialTheme();
    }

    public SettingsManager Settings => _settingsManager;

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

    /// <summary>
    /// 啟動時依設定檢查更新，有新版本時觸發 <see cref="UpdateAvailable"/>
    /// </summary>
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
            Logger.Warning("啟動自動檢查更新失敗: {Message}", ex.Message);
        }
    }

    public void Navigate(string pageKey)
    {
        if (string.IsNullOrWhiteSpace(pageKey))
        {
            return;
        }

        _ui.ActivateMainWindow();

        var targetPage = GetOrCreatePage(pageKey);
        if (targetPage is not null)
        {
            CurrentPage = targetPage;

            switch (targetPage)
            {
                case ManageServerViewModel manageVm:
                    _ = RunSafeAsync(manageVm.List.RefreshServers, "重新整理伺服器清單", Logger);
                    break;
                case ModsViewModel modsVm:
                    _ = RunSafeAsync(modsVm.RefreshServersAsync, "重新整理模組頁面伺服器清單", Logger);
                    break;
            }
        }
        else
        {
            ShowNotification($"找不到頁面：{pageKey}", NotificationType.Error);
        }
    }

    [RelayCommand]
    public async Task ImportServerAsync()
    {
        var vm = new ImportServerViewModel(_serverManager, uiService: _ui);
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
                Navigate("manage");
                if (_pages.TryGetValue("manage", out var page) && page is ManageServerViewModel manageVm)
                {
                    if (!string.IsNullOrWhiteSpace(vm.ImportedServerName))
                    {
                        _ = RunSafeAsync(() => manageVm.List.RefreshAndSelectServerAsync(vm.ImportedServerName), "重新整理並選取匯入伺服器", Logger);
                    }
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
            Logger.Error("建立伺服器資料夾失敗: {Message}", ex.Message);
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
