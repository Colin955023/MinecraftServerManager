using MinecraftServerManager.App.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 主視窗 ViewModel
/// </summary>
public sealed partial class MainViewModel : ViewModelBase
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("MainViewModel");
    private readonly SettingsManager _settingsManager;
    private readonly IServerManager? _serverManager;
    private readonly Dictionary<string, PageViewModel> _pages = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Func<PageViewModel>> _pageFactories = new(StringComparer.OrdinalIgnoreCase);

    [ObservableProperty]
    public partial PageViewModel CurrentPage { get; set; }

    [ObservableProperty]
    public partial string NotificationMessage { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsNotificationVisible { get; set; }

    [ObservableProperty]
    public partial bool IsNotificationError { get; set; }

    private readonly IExternalLauncher? _launcher;
    private readonly IUpdateCheckerService? _updateChecker;
    private readonly IAppUpdateService? _appUpdateService;

    [ObservableProperty]
    public partial bool IsLightTheme { get; set; }

    public event Action<string, string, NotificationLevel>? NotificationRequested;
    public event Action? ResetWindowSizeRequested;

    /// <summary>
    /// 偵測到新版本時觸發，由視窗負責詢問使用者
    /// </summary>
    public event Action<UpdateCheckResult>? UpdateAvailable;

    /// <summary>
    /// 全域 UI 縮放變更事件，由 MainWindow 套用至 LayoutTransform。
    /// </summary>
    public event Action<double>? UiScaleChanged;

    public MainViewModel(
        SettingsManager? settingsManager = null,
        IJavaRuntimeDetector? javaDetector = null,
        IServerManager? serverManager = null,
        IServerBackupService? backupService = null,
        IServerRuntime? serverRuntime = null,
        ILoaderCatalogService? loaderCatalog = null,
        IModManager? modManager = null,
        IModrinthClient? modrinthClient = null,
        IUpdateCheckerService? updateChecker = null,
        IExternalLauncher? launcher = null,
        IMinecraftJavaRequirementService? javaRequirementService = null,
        IJavaInstaller? javaInstaller = null,
        IUiService? uiService = null,
        IAppUpdateService? appUpdateService = null,
        IModDependencyPlanner? dependencyPlanner = null,
        IModListExporter? modListExporter = null,
        IServerDirectorySizeService? directorySizeService = null,
        IServerIntegrityService? integrityService = null)
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _settingsManager = settingsManager ?? new SettingsManager();
        _serverManager = serverManager;
        _launcher = launcher;
        _updateChecker = updateChecker;
        _appUpdateService = appUpdateService;

        var createVm = new CreateServerViewModel(
            javaDetector,
            serverManager,
            loaderCatalog,
            ShowNotification,
            launcher: launcher,
            navigateCallback: (pageKey, serverName) =>
            {
                Navigate(pageKey);
                if (!string.IsNullOrWhiteSpace(serverName)
                    && GetOrCreatePage("manage") is ManageServerViewModel manageVm)
                {
                    _ = manageVm.RefreshAndSelectServerAsync(serverName);
                }
            },
            javaRequirementService: javaRequirementService,
            javaInstaller: javaInstaller,
            serverRuntime: serverRuntime,
            uiService: _ui);

        _pages["create"] = createVm;
        _pageFactories["manage"] = () => new ManageServerViewModel(
            _settingsManager,
            serverManager,
            backupService,
            serverRuntime,
            null,
            null,
            null,
            Navigate,
            ShowNotification,
            launcher,
            javaDetector,
            javaRequirementService,
            uiService: _ui,
            directorySizeService: directorySizeService,
            integrityService: integrityService);
        _pageFactories["mods"] = () => new ModsViewModel(
            serverManager,
            modManager,
            modrinthClient,
            ShowNotification,
            launcher,
            dependencyPlanner: dependencyPlanner,
            modListExporter: modListExporter,
            uiService: _ui);
        _pageFactories["about_preferences"] = () => new AboutPreferencesViewModel(
            _settingsManager,
            updateChecker,
            SetThemeMode,
            () => ResetWindowSizeRequested?.Invoke(),
            ShowNotification,
            launcher,
            scale => UiScaleChanged?.Invoke(scale),
            uiService: _ui,
            appUpdateService: _appUpdateService);

        CurrentPage = createVm;

        ApplyInitialTheme();
        SystemEvents.UserPreferenceChanged += OnUserPreferenceChanged;
    }

    public string PageTitle => CurrentPage.Title;

    public string PageSubtitle => CurrentPage.Subtitle;

    public SettingsManager Settings => _settingsManager;

    public IUpdateCheckerService? UpdateChecker => _updateChecker;

    public IExternalLauncher? Launcher => _launcher;

    public ManageServerViewModel ManageServerPage => (ManageServerViewModel)GetOrCreatePage("manage")!;

    public AboutPreferencesViewModel? AboutPreferences => GetOrCreatePage("about_preferences") as AboutPreferencesViewModel;

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
    [RelayCommand]
    public async Task CheckForUpdateOnStartupAsync(CancellationToken cancellationToken = default)
    {
        if (_updateChecker is null || !_settingsManager.IsAutoUpdateEnabled())
        {
            return;
        }

        try
        {
            UpdateCheckResult result = await _updateChecker.CheckForUpdateAsync(cancellationToken).ConfigureAwait(true);
            if (result.HasUpdate)
            {
                UpdateAvailable?.Invoke(result);
                if (AboutPreferences is not null)
                {
                    await AboutPreferences.HandleUpdateResultAsync(result, cancellationToken).ConfigureAwait(true);
                }
                else
                {
                    string cleanedNotes = AboutPreferencesViewModel.CleanReleaseNotes(result.ReleaseNotes);
                    if (_ui.Confirm(
                        $"發現新版本 {result.LatestVersion} (目前版本：{result.CurrentVersion})！\n\n更新內容：\n{cleanedNotes}\n\n是否立即更新主程式？",
                        "發現新版本"))
                    {
                        OpenReleasePage(result.ReleasePageUrl);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("啟動自動檢查更新失敗: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 透過外部啟動器開啟發行頁面
    /// </summary>
    public void OpenReleasePage(string url) => _launcher?.OpenUrl(url, isTrusted: true);

    [RelayCommand]
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
            OnPropertyChanged(nameof(PageTitle));
            OnPropertyChanged(nameof(PageSubtitle));

            switch (targetPage)
            {
                case ManageServerViewModel manageVm:
                    _ = manageVm.RefreshServers();
                    break;
                case ModsViewModel modsVm:
                    _ = modsVm.RefreshServersAsync();
                    break;
            }
        }
        else
        {
            ShowNotification($"找不到頁面：{pageKey}", isError: true);
        }
    }

    [RelayCommand]
    public void ImportServer()
    {
        if (_serverManager is not null)
        {
            var vm = new ImportServerViewModel(_serverManager,
            uiService: _ui);
            if (_ui.ShowImportServer(vm) == true)
            {
                ShowNotification("伺服器匯入成功！已更新至伺服器管理清單", false);
                Navigate("manage");
                if (_pages.TryGetValue("manage", out var page) && page is ManageServerViewModel manageVm)
                {
                    if (!string.IsNullOrWhiteSpace(vm.ImportedServerName))
                    {
                        _ = manageVm.RefreshAndSelectServerAsync(vm.ImportedServerName);
                    }
                    else
                    {
                        _ = manageVm.RefreshServers();
                    }
                }
            }
            return;
        }

        ShowNotification("開啟伺服器匯入對話方塊 (支援資料夾與 ZIP 壓縮檔)", false);
    }

    [RelayCommand]
    public Task OpenServersFolder()
    {
        string path = _settingsManager.GetServersRoot();
        if (string.IsNullOrWhiteSpace(path))
        {
            ShowNotification("尚未設定伺服器資料夾", true);
            return Task.CompletedTask;
        }

        SafeFileSystem.CreateDirectory(path);

        if (_launcher is not null && !_launcher.OpenFolder(path, isTrusted: true))
        {
            ShowNotification($"無法開啟資料夾：{path}", true);
        }

        return Task.CompletedTask;
    }

    [RelayCommand]
    public void DismissNotification()
    {
        IsNotificationVisible = false;
        NotificationMessage = string.Empty;
    }

    [RelayCommand]
    public void ToggleTheme()
    {
        IsLightTheme = !IsLightTheme;
        string mode = IsLightTheme ? "light" : "dark";
        _settingsManager.SetThemeMode(mode);
        NotificationMessage = $"已切換為{(IsLightTheme ? "淺色" : "深色")}主題";
        IsNotificationVisible = true;
    }

    public void ShowNotification(string message, bool isError = false)
    {
        NotificationMessage = message;
        IsNotificationError = isError;
        IsNotificationVisible = true;
        if (isError)
        {
            NotificationRequested?.Invoke("錯誤", message, NotificationLevel.Error);
        }
        else
        {
            _ui.ShowToast(message, "提示", ToastType.Info);
        }
    }

    public void SetThemeMode(string mode) =>
        IsLightTheme = mode switch
        {
            "light" => true,
            "dark" => false,
            _ => SystemThemeService.IsSystemLightTheme(),
        };

    private void OnUserPreferenceChanged(object? sender, UserPreferenceChangedEventArgs e)
    {
        if (e.Category is UserPreferenceCategory.General or UserPreferenceCategory.Color)
        {
            if (string.Equals(_settingsManager.GetThemeMode(), "system", StringComparison.OrdinalIgnoreCase))
            {
                _ui.PostToUi(() => SetThemeMode("system"));
            }
        }
    }

    private void ApplyInitialTheme()
    {
        string themeMode = _settingsManager.GetThemeMode();
        SetThemeMode(themeMode);
    }

    public void UnregisterEvents()
    {
        SystemEvents.UserPreferenceChanged -= OnUserPreferenceChanged;
        DisposePages();
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
