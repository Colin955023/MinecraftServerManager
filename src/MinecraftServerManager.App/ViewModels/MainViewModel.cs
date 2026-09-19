using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 主視窗 ViewModel
/// </summary>
public sealed partial class MainViewModel : ViewModelBase
{
    private readonly SettingsManager _settingsManager;
    private readonly IServerManager? _serverManager;
    private readonly Dictionary<string, PageViewModel> _pages = new(StringComparer.OrdinalIgnoreCase);

    [ObservableProperty]
    private PageViewModel _currentPage;

    [ObservableProperty]
    private string _notificationMessage = string.Empty;

    [ObservableProperty]
    private bool _isNotificationVisible;

    [ObservableProperty]
    private bool _isNotificationError;
    private readonly IExternalLauncher? _launcher;

    [ObservableProperty]
    private bool _isLightTheme;

    public event Action<string, string, NotificationLevel>? NotificationRequested;
    public event Action? ResetWindowSizeRequested;

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
        IExternalLauncher? launcher = null)
    {
        _settingsManager = settingsManager ?? new SettingsManager();
        _serverManager = serverManager;
        _launcher = launcher;

        var createVm = new CreateServerViewModel(javaDetector, serverManager, loaderCatalog, ShowNotification, launcher: launcher);
        var manageVm = new ManageServerViewModel(_settingsManager, serverManager, backupService, serverRuntime, null, null, null, NavigateToPage, ShowNotification, launcher);
        var modsVm = new ModsViewModel(serverManager, modManager, modrinthClient, ShowNotification, launcher);
        var aboutPrefsVm = new AboutPreferencesViewModel(_settingsManager, updateChecker, SetThemeMode, () => ResetWindowSizeRequested?.Invoke(), ShowNotification, launcher);

        _pages["create"] = createVm;
        _pages["manage"] = manageVm;
        _pages["mods"] = modsVm;
        _pages["about_preferences"] = aboutPrefsVm;

        // 預設為「建立伺服器」頁面
        _currentPage = createVm;

        ApplyInitialTheme();
    }

    public PageViewModel CurrentPageValue => CurrentPage;

    public string PageTitle => CurrentPage.Title;

    public string PageSubtitle => CurrentPage.Subtitle;

    public SettingsManager Settings => _settingsManager;

    public AboutPreferencesViewModel? AboutPreferences => _pages.TryGetValue("about_preferences", out var p) ? p as AboutPreferencesViewModel : null;

    [RelayCommand]
    public void Navigate(string pageKey) => NavigateToPage(pageKey);

    [RelayCommand]
    public void ImportServer()
    {
        if (_serverManager is not null)
        {
            var vm = new ImportServerViewModel(_serverManager);
            var dialog = new ImportServerDialog(vm);
            if (dialog.ShowDialog() == true)
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

        ShowNotification("開啟伺服器匯入對話框 (支援資料夾與 ZIP 壓縮檔)", false);
    }

    [RelayCommand]
    public void OpenServersFolder()
    {
        string path = _settingsManager.GetServersRoot();
        if (string.IsNullOrWhiteSpace(path))
        {
            ShowNotification("尚未設定伺服器資料夾", true);
            return;
        }

        if (!Directory.Exists(path))
        {
            Directory.CreateDirectory(path);
        }

        if (_launcher is not null)
        {
            if (_launcher.OpenFolder(path))
            {
                ShowNotification($"已開啟伺服器資料夾：{path}", false);
            }
            else
            {
                ShowNotification($"開啟資料夾失敗：{path}", true);
            }
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
        ShowNotification($"已切換為{(IsLightTheme ? "淺色" : "深色")}主題", isError: false);
    }

    public void ShowNotification(string message, bool isError = false)
    {
        NotificationMessage = message;
        IsNotificationError = isError;
        IsNotificationVisible = true;
        NotificationRequested?.Invoke(isError ? "錯誤" : "提示", message, isError ? NotificationLevel.Error : NotificationLevel.Info);
    }

    public void SetThemeMode(string mode)
    {
        IsLightTheme = mode switch
        {
            "light" => true,
            "dark" => false,
            _ => false, // system 預設深色
        };
    }

    private void NavigateToPage(string pageKey)
    {
        if (string.IsNullOrWhiteSpace(pageKey))
        {
            return;
        }

        if (_pages.TryGetValue(pageKey, out var targetPage))
        {
            CurrentPage = targetPage;
            OnPropertyChanged(nameof(PageTitle));
            OnPropertyChanged(nameof(PageSubtitle));
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
}
