using MinecraftServerManager.App.Services;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
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
        IAppUpdateService? appUpdateService = null)
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
                NavigateToPage(pageKey);
                if (!string.IsNullOrWhiteSpace(serverName)
                    && _pages.TryGetValue("manage", out var page)
                    && page is ManageServerViewModel manageVm)
                {
                    _ = manageVm.RefreshAndSelectServerAsync(serverName);
                }
            },
            javaRequirementService: javaRequirementService,
            javaInstaller: javaInstaller,
            serverRuntime: serverRuntime,
            uiService: _ui);
        var manageVm = new ManageServerViewModel(
            _settingsManager,
            serverManager,
            backupService,
            serverRuntime,
            null,
            null,
            null,
            NavigateToPage,
            ShowNotification,
            launcher,
            javaDetector,
            javaRequirementService,
            uiService: _ui);
        var modsVm = new ModsViewModel(serverManager, modManager, modrinthClient, ShowNotification, launcher,
            uiService: _ui);
        var aboutPrefsVm = new AboutPreferencesViewModel(
            _settingsManager,
            updateChecker,
            SetThemeMode,
            () => ResetWindowSizeRequested?.Invoke(),
            ShowNotification,
            launcher,
            scale => UiScaleChanged?.Invoke(scale),
            uiService: _ui,
            appUpdateService: _appUpdateService);

        _pages["create"] = createVm;
        _pages["manage"] = manageVm;
        _pages["mods"] = modsVm;
        _pages["about_preferences"] = aboutPrefsVm;
        CurrentPage = createVm;

        ApplyInitialTheme();
        SystemEvents.UserPreferenceChanged += OnUserPreferenceChanged;
    }


    public string PageTitle => CurrentPage.Title;

    public string PageSubtitle => CurrentPage.Subtitle;

    public SettingsManager Settings => _settingsManager;

    public IUpdateCheckerService? UpdateChecker => _updateChecker;

    public IExternalLauncher? Launcher => _launcher;

    public AboutPreferencesViewModel? AboutPreferences => _pages.TryGetValue("about_preferences", out var p) ? p as AboutPreferencesViewModel : null;

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
    public void Navigate(string pageKey) => NavigateToPage(pageKey);

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
                NavigateToPage("manage");
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
    public async Task OpenServersFolder()
    {
        string path = _settingsManager.GetServersRoot();
        if (string.IsNullOrWhiteSpace(path))
        {
            ShowNotification("尚未設定伺服器資料夾", true);
            return;
        }

        await Task.Run(() => Directory.CreateDirectory(path)).ConfigureAwait(true);

        if (_launcher is not null && !_launcher.OpenFolder(path, isTrusted: true))
        {
            ShowNotification($"無法開啟資料夾：{path}", true);
        }
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
        NotificationRequested?.Invoke(isError ? "錯誤" : "提示", message, isError ? NotificationLevel.Error : NotificationLevel.Info);
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

    private void NavigateToPage(string pageKey)
    {
        if (string.IsNullOrWhiteSpace(pageKey))
        {
            return;
        }

        _ui.ActivateMainWindow();

        if (_pages.TryGetValue(pageKey, out var targetPage))
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

    private void ApplyInitialTheme()
    {
        string themeMode = _settingsManager.GetThemeMode();
        SetThemeMode(themeMode);
    }

    public void UnregisterEvents() => SystemEvents.UserPreferenceChanged -= OnUserPreferenceChanged;
}
