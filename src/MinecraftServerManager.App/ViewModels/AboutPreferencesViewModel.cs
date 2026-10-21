using MinecraftServerManager.App.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 關於與偏好設定整合頁面 ViewModel
/// </summary>
public sealed partial class AboutPreferencesViewModel : PageViewModel
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("AboutPreferencesViewModel");

    private readonly IUiService _ui;

    private readonly SettingsManager? _settingsManager;
    private readonly IUpdateCheckerService? _updateChecker;
    private readonly IAppUpdateService? _appUpdateService;
    private readonly IExternalLauncher? _launcher;
    private readonly Action<string>? _onThemeModeChanged;
    private readonly Action? _onResetWindowSizeRequested;
    private readonly Action<double>? _onUiScaleChanged;
    private readonly Action<string, bool>? _notificationSink;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsManualCheckVisible))]
    public partial bool IsAutoUpdateEnabled { get; set; } = true;

    public bool IsManualCheckVisible => !IsAutoUpdateEnabled;

    [ObservableProperty]
    public partial int SelectedThemeModeIndex { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsCustomScaleVisible))]
    public partial int SelectedUiScaleIndex { get; set; } = 1;

    [ObservableProperty]
    public partial string CustomUiScaleText { get; set; } = "100";

    /// <summary>
    /// 選擇「自訂」時顯示輸入框與百分比提示。
    /// </summary>
    public bool IsCustomScaleVisible => SelectedUiScaleIndex == UiScaleOptions.Count - 1;

    [ObservableProperty]
    public partial string ScreenResolutionInfo { get; set; } = "目前螢幕解析度: 1920 × 1080";

    [ObservableProperty]
    public partial string CurrentWindowSizeInfo { get; set; } = "目前主視窗大小: 1350 × 820";

    public AboutPreferencesViewModel(
        SettingsManager? settingsManager = null,
        IUpdateCheckerService? updateChecker = null,
        Action<string>? onThemeModeChanged = null,
        Action? onResetWindowSizeRequested = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null,
        Action<double>? onUiScaleChanged = null,
        IUiService? uiService = null,
        IAppUpdateService? appUpdateService = null)
        : base("about_preferences", "關於與設定", "檢視應用程式資訊、授權條款與視窗偏好設定")
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _settingsManager = settingsManager;
        _updateChecker = updateChecker;
        _appUpdateService = appUpdateService;
        _onThemeModeChanged = onThemeModeChanged;
        _onResetWindowSizeRequested = onResetWindowSizeRequested;
        _onUiScaleChanged = onUiScaleChanged;
        _notificationSink = notificationSink;
        _launcher = launcher;

        if (_settingsManager is not null)
        {
            IsAutoUpdateEnabled = _settingsManager.IsAutoUpdateEnabled();
            string theme = _settingsManager.GetThemeMode();
            SelectedThemeModeIndex = theme switch
            {
                "light" => 1,
                "dark" => 2,
                _ => 0,
            };

            double scale = _settingsManager.GetUiScale();
            CustomUiScaleText = ((int)Math.Round(scale * 100)).ToString(System.Globalization.CultureInfo.InvariantCulture);
            SelectedUiScaleIndex = PresetScales.IndexOf(scale) is int idx && idx >= 0 ? idx : UiScaleOptions.Count - 1;
        }
    }

    public static string AppVersion => AppInfo.Version;

    public static string AppDescription => AppInfo.AppName;

    public static string GithubUrl => AppInfo.RepositoryUrl;

    public static string AppAuthor => AppInfo.Author;

    public static string AppLicense => AppInfo.License;

    public static string AppTargetFramework => AppInfo.TargetFramework;

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
    public void OpenGithub() => _launcher?.OpenUrl(GithubUrl, isTrusted: true);

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
                await HandleUpdateResultAsync(result).ConfigureAwait(true);
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

    /// <summary>
    /// 處理檢查更新結果：提示使用者更新，若使用者確認則執行安全下載驗證與重啟流程
    /// </summary>
    public async Task HandleUpdateResultAsync(UpdateCheckResult result, CancellationToken cancellationToken = default)
    {
        string cleanedNotes = CleanReleaseNotes(result.ReleaseNotes);
        bool confirm = _ui.Confirm(
            $"發現新版本 {result.LatestVersion} (目前版本：{result.CurrentVersion})！\n\n更新內容：\n{cleanedNotes}\n\n是否立即更新主程式？",
            "發現新版本",
            UiMessageLevel.Question);

        if (!confirm)
        {
            // 否：本次取消，下次重新啟動時仍會再次詢問
            return;
        }

        if (string.IsNullOrWhiteSpace(result.DownloadUrl) || _appUpdateService is null)
        {
            bool openWeb = _ui.Confirm(
                "目前發布版本不支援直接自動安裝，是否前往 GitHub 發布頁面手動下載？",
                "手動下載更新",
                UiMessageLevel.Information);
            if (openWeb)
            {
                _launcher?.OpenUrl(result.ReleasePageUrl, isTrusted: true);
            }
            return;
        }

        var progressDialog = _ui.ShowModOperationProgress("主程式自動更新", "準備下載更新檔案...");
        try
        {
            var progress = new Progress<(int Percentage, string StatusMessage)>(p =>
            {
                progressDialog.UpdateProgress(p.Percentage, 100, p.StatusMessage);
            });

            string installerPath = await _appUpdateService.DownloadAndVerifyUpdateAsync(result, progress, cancellationToken).ConfigureAwait(true);

            progressDialog.UpdateProgress(100, 100, "更新檔案驗證成功，即將重新啟動並套用更新...");
            await Task.Delay(1000, cancellationToken).ConfigureAwait(true);
            progressDialog.Close();

            _appUpdateService.ApplyUpdateAndRestart(installerPath);
            _ui.PostToUi(() =>
            {
                _ui.ShutdownApplication(0);
            });
        }
        catch (OperationCanceledException)
        {
            progressDialog.Close();
        }
        catch (Exception ex)
        {
            progressDialog.Close();
            Logger.Error(ex, "主程式更新流程異常: {Message}", ex.Message);
            bool fallback = _ui.Confirm(
                $"更新主程式失敗：{ex.Message}\n\n是否改為前往 GitHub 手動下載最新版本？",
                "更新失敗",
                UiMessageLevel.Error);
            if (fallback)
            {
                _launcher?.OpenUrl(result.ReleasePageUrl, isTrusted: true);
            }
        }
    }

    public static string CleanReleaseNotes(string? notes)
    {
        if (string.IsNullOrWhiteSpace(notes))
        {
            return "(無更新紀錄)";
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
            return "(無更新紀錄)";
        }

        var trimmedLines = keptLines.Skip(start).Take(end - start + 1).ToList();

        if (trimmedLines.Count > 15)
        {
            trimmedLines = [.. trimmedLines.Take(15)];
            trimmedLines.Add("... (完整內容請檢視發行頁面)");
        }

        return string.Join(Environment.NewLine, trimmedLines);
    }

    [RelayCommand]
    private void ResetToDefaultSize()
    {
        if (_ui.Confirm("確定要將主視窗大小與位置重設為預設值嗎？", "確認重設視窗大小"))
        {
            _onResetWindowSizeRequested?.Invoke();
        }
    }

    [RelayCommand]
    private void ResetAllSettings()
    {
        if (!_ui.Confirm("確定要將所有偏好設定還原為原廠預設值嗎？", "確認還原預設", UiMessageLevel.Warning))
        {
            return;
        }

        IsAutoUpdateEnabled = true;
        SelectedThemeModeIndex = 0;

        SelectedUiScaleIndex = 1;
        CustomUiScaleText = "100";

        _onResetWindowSizeRequested?.Invoke();
    }


    public void UpdateDisplayInfo(int screenWidth, int screenHeight, int windowWidth, int windowHeight)
    {
        ScreenResolutionInfo = $"目前螢幕解析度: {screenWidth} × {screenHeight}";
        CurrentWindowSizeInfo = $"目前主視窗大小: {windowWidth} × {windowHeight}";
    }
}
