using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 關於與偏好設定整合頁面 ViewModel
/// </summary>
public sealed partial class AboutPreferencesViewModel : PageViewModel
{
    private readonly SettingsManager? _settingsManager;
    private readonly IUpdateCheckerService? _updateChecker;
    private readonly IExternalLauncher? _launcher;
    private readonly Action<string>? _onThemeModeChanged;
    private readonly Action? _onResetWindowSizeRequested;
    private readonly Action<string, bool>? _notificationSink;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsManualCheckVisible))]
    private bool _isAutoUpdateEnabled = true;

    public bool IsManualCheckVisible => !IsAutoUpdateEnabled;

    [ObservableProperty]
    private bool _isRememberSizePositionEnabled = true;

    [ObservableProperty]
    private bool _isAutoCenterEnabled = true;

    [ObservableProperty]
    private int _selectedThemeModeIndex;

    [ObservableProperty]
    private string _screenResolutionInfo = "目前螢幕解析度: 1920 × 1080";

    [ObservableProperty]
    private string _currentWindowSizeInfo = "目前主視窗大小: 1350 × 820";

    public AboutPreferencesViewModel(
        SettingsManager? settingsManager = null,
        IUpdateCheckerService? updateChecker = null,
        Action<string>? onThemeModeChanged = null,
        Action? onResetWindowSizeRequested = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null)
        : base("about_preferences", "關於與設定", "查看應用程式資訊、授權條款與視窗偏好設定")
    {
        _settingsManager = settingsManager;
        _updateChecker = updateChecker;
        _onThemeModeChanged = onThemeModeChanged;
        _onResetWindowSizeRequested = onResetWindowSizeRequested;
        _notificationSink = notificationSink;
        _launcher = launcher;

        if (_settingsManager is not null)
        {
            _isAutoUpdateEnabled = _settingsManager.IsAutoUpdateEnabled();
            _isRememberSizePositionEnabled = _settingsManager.IsRememberSizePositionEnabled();
            _isAutoCenterEnabled = _settingsManager.IsAutoCenterEnabled();
            string theme = _settingsManager.GetThemeMode();
            _selectedThemeModeIndex = theme switch
            {
                "light" => 1,
                "dark" => 2,
                _ => 0,
            };
        }
    }

    public string AppName { get; } = "Minecraft Server Manager";

    public string AppVersion { get; } = "2.0.0";

    public string AppDescription { get; } = "Minecraft 伺服器管理器";

    public string Developer { get; } = "Colin955023";

    public string GithubOwner { get; } = "Colin955023";

    public string GithubRepo { get; } = "MinecraftServerManager";

    public string GithubUrl => $"https://github.com/{GithubOwner}/{GithubRepo}";

    public string TargetFramework { get; } = ".NET 10 (WPF)";

    public string License { get; } = "GNU General Public License v3.0 (GPL-3.0)";

    public static IReadOnlyList<string> ThemeModes { get; } = ["依照系統設定", "淺色", "深色"];

    partial void OnIsAutoUpdateEnabledChanged(bool value)
    {
        _settingsManager?.SetAutoUpdateEnabled(value);
    }

    partial void OnIsRememberSizePositionEnabledChanged(bool value)
    {
        _settingsManager?.SetRememberSizePosition(value);
    }

    partial void OnIsAutoCenterEnabledChanged(bool value)
    {
        _settingsManager?.SetAutoCenter(value);
    }

    partial void OnSelectedThemeModeIndexChanged(int value)
    {
        var mode = value switch
        {
            1 => "light",
            2 => "dark",
            _ => "system",
        };

        _settingsManager?.SetThemeMode(mode);
        _onThemeModeChanged?.Invoke(mode);
    }

    [RelayCommand]
    public void OpenGithub() => _launcher?.OpenUrl(GithubUrl);

    [RelayCommand]
    public void OpenPrismLauncher() => _launcher?.OpenUrl("https://prismlauncher.org/");

    [RelayCommand]
    private async Task CheckForUpdatesAsync()
    {
        _notificationSink?.Invoke("正在檢查 GitHub 最新版本...", false);
        if (_updateChecker is null)
        {
            _notificationSink?.Invoke("未設定更新檢查服務", true);
            return;
        }

        try
        {
            var result = await _updateChecker.CheckForUpdateAsync();
            if (result.HasUpdate)
            {
                _notificationSink?.Invoke($"發現新版本 {result.LatestVersion}！正在為您開啟發布頁面", false);
                _launcher?.OpenUrl(result.ReleasePageUrl);
            }
            else
            {
                _notificationSink?.Invoke($"目前已是最新版本 ({result.CurrentVersion})", false);
            }
        }
        catch (Exception ex)
        {
            _notificationSink?.Invoke($"檢查更新失敗：{ex.Message}", true);
        }
    }

    [RelayCommand]
    private void ResetToDefaultSize() => _onResetWindowSizeRequested?.Invoke();

    [RelayCommand]
    private void ResetAllSettings()
    {
        IsRememberSizePositionEnabled = true;
        IsAutoCenterEnabled = true;
        IsAutoUpdateEnabled = true;
        SelectedThemeModeIndex = 0;

        _settingsManager?.SetRememberSizePosition(true);
        _settingsManager?.SetAutoCenter(true);
        _settingsManager?.SetAutoUpdateEnabled(true);
        _settingsManager?.SetThemeMode("system");

        _notificationSink?.Invoke("已恢復所有偏好設定為預設值", false);
    }

    [RelayCommand]
    private void ApplySettings()
    {
        string mode = SelectedThemeModeIndex switch
        {
            1 => "light",
            2 => "dark",
            _ => "system",
        };

        _settingsManager?.SetRememberSizePosition(IsRememberSizePositionEnabled);
        _settingsManager?.SetAutoCenter(IsAutoCenterEnabled);
        _settingsManager?.SetAutoUpdateEnabled(IsAutoUpdateEnabled);
        _settingsManager?.SetThemeMode(mode);
        _onThemeModeChanged?.Invoke(mode);

        _notificationSink?.Invoke("設定已成功套用！", false);
    }

    public void UpdateDisplayInfo(int screenWidth, int screenHeight, int windowWidth, int windowHeight)
    {
        ScreenResolutionInfo = $"目前螢幕解析度: {screenWidth} × {screenHeight}";
        CurrentWindowSizeInfo = $"目前主視窗大小: {windowWidth} × {windowHeight}";
    }
}
