using System.Windows;
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
    private readonly Action<double>? _onUiScaleChanged;
    private readonly Action<string, bool>? _notificationSink;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsManualCheckVisible))]
    private bool _isAutoUpdateEnabled = true;

    public bool IsManualCheckVisible => !IsAutoUpdateEnabled;

    [ObservableProperty]
    private int _selectedThemeModeIndex;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsCustomScaleVisible))]
    private int _selectedUiScaleIndex = 1;

    [ObservableProperty]
    private string _customUiScaleText = "100";

    /// <summary>
    /// 選擇「自訂」時顯示輸入框與百分比提示。
    /// </summary>
    public bool IsCustomScaleVisible => SelectedUiScaleIndex == UiScaleOptions.Count - 1;

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
        IExternalLauncher? launcher = null,
        Action<double>? onUiScaleChanged = null)
        : base("about_preferences", "關於與設定", "查看應用程式資訊、授權條款與視窗偏好設定")
    {
        _settingsManager = settingsManager;
        _updateChecker = updateChecker;
        _onThemeModeChanged = onThemeModeChanged;
        _onResetWindowSizeRequested = onResetWindowSizeRequested;
        _onUiScaleChanged = onUiScaleChanged;
        _notificationSink = notificationSink;
        _launcher = launcher;

        if (_settingsManager is not null)
        {
            _isAutoUpdateEnabled = _settingsManager.IsAutoUpdateEnabled();
            string theme = _settingsManager.GetThemeMode();
            _selectedThemeModeIndex = theme switch
            {
                "light" => 1,
                "dark" => 2,
                _ => 0,
            };

            double scale = _settingsManager.GetUiScale();
            _customUiScaleText = ((int)Math.Round(scale * 100)).ToString(System.Globalization.CultureInfo.InvariantCulture);
            _selectedUiScaleIndex = PresetScales.IndexOf(scale) is int idx && idx >= 0 ? idx : UiScaleOptions.Count - 1;
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

    public static IReadOnlyList<string> UiScaleOptions { get; } = ["75%", "100% (預設)", "125%", "150%", "200%", "自訂"];

    private static readonly List<double> PresetScales = [0.75, 1.0, 1.25, 1.5, 2.0];

    /// <summary>
    /// 由目前選擇換算出實際縮放倍率。
    /// </summary>
    public double ResolveUiScale()
    {
        if (SelectedUiScaleIndex >= 0 && SelectedUiScaleIndex < PresetScales.Count)
        {
            return PresetScales[SelectedUiScaleIndex];
        }

        if (double.TryParse(CustomUiScaleText, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out double percent)
            && percent > 0)
        {
            return Math.Clamp(Math.Round(percent / 100.0, 2), 0.5, 3.0);
        }

        return 1.0;
    }

    partial void OnIsAutoUpdateEnabledChanged(bool value) => _settingsManager?.SetAutoUpdateEnabled(value);

    partial void OnSelectedThemeModeIndexChanged(int value)
    {
        string mode = value switch
        {
            1 => "light",
            2 => "dark",
            _ => "system",
        };

        _settingsManager?.SetThemeMode(mode);
        _onThemeModeChanged?.Invoke(mode);
    }

    partial void OnSelectedUiScaleIndexChanged(int value)
    {
        double scale = ResolveUiScale();
        _settingsManager?.SetUiScale(scale);
        _onUiScaleChanged?.Invoke(scale);
    }

    partial void OnCustomUiScaleTextChanged(string value)
    {
        if (SelectedUiScaleIndex == UiScaleOptions.Count - 1)
        {
            double scale = ResolveUiScale();
            _settingsManager?.SetUiScale(scale);
            _onUiScaleChanged?.Invoke(scale);
        }
    }

    [RelayCommand]
    public void OpenGithub() => _launcher?.OpenUrl(GithubUrl);

    [RelayCommand]
    public void OpenPrismLauncher() => _launcher?.OpenUrl("https://prismlauncher.org/");

    [RelayCommand]
    private async Task CheckForUpdatesAsync()
    {
        if (_updateChecker is null)
        {
            return;
        }

        try
        {
            var result = await _updateChecker.CheckForUpdateAsync();
            if (result.HasUpdate)
            {
                string cleanedNotes = CleanReleaseNotes(result.ReleaseNotes);
                var confirm = MessageBox.Show(
                    $"發現新版本 {result.LatestVersion} (目前版本：{result.CurrentVersion})！\n\n更新內容：\n{cleanedNotes}\n\n是否立即前往 GitHub 下載更新？",
                    "發現新版本",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Information);

                if (confirm == MessageBoxResult.Yes)
                {
                    _launcher?.OpenUrl(result.ReleasePageUrl);
                }
            }
            else
            {
                _notificationSink?.Invoke($"目前已是最新版本 (v{result.CurrentVersion})", false);
            }
        }
        catch (Exception ex)
        {
            _notificationSink?.Invoke($"檢查更新失敗：{ex.Message}", true);
        }
    }

    public static string CleanReleaseNotes(string? notes)
    {
        if (string.IsNullOrWhiteSpace(notes))
        {
            return "(無更新日誌)";
        }

        var keptLines = new List<string>();

        foreach (var lineSpan in notes.AsSpan().EnumerateLines())
        {
            var trimmed = lineSpan.Trim();
            if (trimmed.Contains("===", StringComparison.Ordinal))
            {
                continue;
            }

            keptLines.Add(lineSpan.ToString());
        }

        int start = 0;
        while (start < keptLines.Count && string.IsNullOrWhiteSpace(keptLines[start]))
        {
            start++;
        }

        int end = keptLines.Count - 1;
        while (end >= start && string.IsNullOrWhiteSpace(keptLines[end]))
        {
            end--;
        }

        if (start > end)
        {
            return "(無更新日誌)";
        }

        var trimmedLines = keptLines.Skip(start).Take(end - start + 1).ToList();

        if (trimmedLines.Count > 15)
        {
            trimmedLines = [.. trimmedLines.Take(15)];
            trimmedLines.Add("... (完整內容請查看發行頁面)");
        }

        return string.Join(Environment.NewLine, trimmedLines);
    }

    [RelayCommand]
    private void ResetToDefaultSize()
    {
        if (Views.DialogHelper.Confirm("確定要將主視窗大小與位置重設為預設值嗎？", "確認重設視窗大小"))
        {
            _onResetWindowSizeRequested?.Invoke();
        }
    }

    [RelayCommand]
    private void ResetAllSettings()
    {
        if (!Views.DialogHelper.Confirm("確定要恢復所有偏好設定為原廠預設值嗎？", "確認恢復預設", MessageBoxImage.Warning))
        {
            return;
        }

        IsAutoUpdateEnabled = true;
        SelectedThemeModeIndex = 0;

        SelectedUiScaleIndex = 1;
        CustomUiScaleText = "100";

        _settingsManager?.SetAutoUpdateEnabled(true);
        _settingsManager?.SetThemeMode("system");
        _settingsManager?.SetUiScale(1.0);
        _onUiScaleChanged?.Invoke(1.0);

        _notificationSink?.Invoke("已恢復所有偏好設定為預設值", false);
    }


    public void UpdateDisplayInfo(int screenWidth, int screenHeight, int windowWidth, int windowHeight)
    {
        ScreenResolutionInfo = $"目前螢幕解析度: {screenWidth} × {screenHeight}";
        CurrentWindowSizeInfo = $"目前主視窗大小: {windowWidth} × {windowHeight}";
    }
}
