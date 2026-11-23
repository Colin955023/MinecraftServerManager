using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>關於與偏好設定整合頁面 ViewModel；設定變更以防抖批次寫檔，處置時寫入未儲存變更</summary>
public sealed partial class AboutPreferencesViewModel : PageViewModel, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AboutPreferencesViewModel));
    private static readonly TimeSpan SaveDebounce = TimeSpan.FromMilliseconds(500);
    private static readonly string[] ThemeModeNames = ["依照系統設定", "淺色", "深色"];

    private readonly IUiService _ui;
    private readonly ISettingsManager _settingsManager;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly IUiTimer _saveTimer;
    private readonly IUpdateCheckerService _updateChecker;
    private readonly IAppUpdateService _appUpdateService;
    private readonly IExternalLauncher _launcher;
    private readonly IAccentColorService _accentColorService;
    private readonly Action<string> _onThemeModeChanged;
    private readonly Action _onResetWindowSizeRequested;
    private readonly SemaphoreSlim _saveGate = new(1, 1);
    private bool _suppressSave;
    private bool _savePending;
    private int _updateInProgress;
    private bool _disposed;

    public AboutPreferencesViewModel(
        IUiService uiService,
        ISettingsManager settingsManager,
        ServerStopCoordinator stopCoordinator,
        IUpdateCheckerService updateChecker,
        Action<string> onThemeModeChanged,
        Action onResetWindowSizeRequested,
        IExternalLauncher launcher,
        IAppUpdateService appUpdateService,
        IAccentColorService accentColorService)
        : base("關於與設定")
    {
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(stopCoordinator);
        ArgumentNullException.ThrowIfNull(updateChecker);
        ArgumentNullException.ThrowIfNull(onThemeModeChanged);
        ArgumentNullException.ThrowIfNull(onResetWindowSizeRequested);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(appUpdateService);
        ArgumentNullException.ThrowIfNull(accentColorService);

        _ui = uiService;
        _settingsManager = settingsManager;
        _stopCoordinator = stopCoordinator;
        _updateChecker = updateChecker;
        _appUpdateService = appUpdateService;
        _onThemeModeChanged = onThemeModeChanged;
        _onResetWindowSizeRequested = onResetWindowSizeRequested;
        _launcher = launcher;
        _accentColorService = accentColorService;
        _saveTimer = _ui.CreateUiTimer(SaveDebounce, () => _ = RunSafeAsync(FlushPendingSaveAsync, "儲存偏好設定", Logger));

        _suppressSave = true;
        IsAutoUpdateEnabled = _settingsManager.IsAutoUpdateEnabled();
        IsAutoBackupBeforeStartEnabled = _settingsManager.IsAutoBackupBeforeStartEnabled();
        BackupRetentionCount = _settingsManager.GetBackupRetentionCount();
        SelectedThemeModeIndex = _settingsManager.GetThemeMode() switch
        {
            "light" => 1,
            "dark" => 2,
            _ => 0,
        };

        string? savedAccent = _settingsManager.GetCustomAccentColor();
        if (!string.IsNullOrWhiteSpace(savedAccent) && AccentColorService.ParseColor(savedAccent) is Windows.UI.Color parsed)
        {
            // 強調色已於啟動時套用，此處只同步顯示狀態
            ApplyAccentState(savedAccent, parsed);
        }
        else
        {
            ApplyAccentState(null, _accentColorService.GetSystemAccentColor());
        }

        _suppressSave = false;
        _accentColorService.AccentColorChanged += OnAccentColorChanged;
    }

    public static string AppVersion => AppInfo.Version;

    public static string AppDescription => AppInfo.AppName;

    public static string AppAuthor => AppInfo.Author;

    public static string AppTargetFramework => AppInfo.TargetFramework;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsManualCheckVisible))]
    public partial bool IsAutoUpdateEnabled { get; set; } = true;

    public bool IsManualCheckVisible => !IsAutoUpdateEnabled;

    [ObservableProperty]
    public partial bool IsAutoBackupBeforeStartEnabled { get; set; }

    [ObservableProperty]
    public partial double BackupRetentionCount { get; set; } = ServerDefaults.DefaultBackupRetentionCount;

    [ObservableProperty]
    public partial int SelectedThemeModeIndex { get; set; }

    [ObservableProperty]
    public partial string ScreenResolutionInfo { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string CurrentWindowSizeInfo { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string? CustomAccentColor { get; set; }

    [ObservableProperty]
    public partial string AccentColorSummaryText { get; set; } = "使用 Windows 系統強調色（預設）";

    [ObservableProperty]
    public partial Windows.UI.Color CurrentAccentColor { get; set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ResetAccentColorCommand))]
    public partial bool IsCustomAccentColor { get; set; }

    public IReadOnlyList<string> ThemeModes { get; } = ThemeModeNames;

    private string SelectedThemeMode => SelectedThemeModeIndex switch
    {
        1 => "light",
        2 => "dark",
        _ => "system",
    };

    /// <summary>依主視窗即時尺寸更新「目前螢幕解析度」與「目前主視窗大小」顯示文字</summary>
    public void UpdateWindowMetrics(WindowMetrics metrics)
    {
        int percent = (int)Math.Round(metrics.Scale * 100);
        string scaleText = percent == 100 ? string.Empty : $"（縮放 {percent}%）";
        ScreenResolutionInfo = $"目前螢幕解析度：{metrics.ScreenWidth} × {metrics.ScreenHeight}{scaleText}";
        CurrentWindowSizeInfo = $"目前主視窗大小：{metrics.WindowWidth} × {metrics.WindowHeight}";
    }

    partial void OnIsAutoUpdateEnabledChanged(bool value) => ScheduleSave();

    partial void OnIsAutoBackupBeforeStartEnabledChanged(bool value) => ScheduleSave();

    partial void OnBackupRetentionCountChanged(double value)
    {
        if (double.IsNaN(value))
        {
            BackupRetentionCount = _settingsManager.GetBackupRetentionCount();
            return;
        }

        int rounded = (int)Math.Clamp(Math.Round(value), ServerDefaults.MinBackupRetentionCount, ServerDefaults.MaxBackupRetentionCount);
        if (rounded != value)
        {
            BackupRetentionCount = rounded;
            return;
        }

        ScheduleSave();
    }

    partial void OnSelectedThemeModeIndexChanged(int value)
    {
        if (_suppressSave)
        {
            return;
        }

        ScheduleSave();
        _onThemeModeChanged(SelectedThemeMode);
    }

    [RelayCommand]
    private void OpenGithub() => OpenUrl(AppInfo.RepositoryUrl);

    [RelayCommand]
    private void OpenLicense() => OpenUrl(AppInfo.LicenseUrl);

    private void OpenUrl(string url) => _ui.OpenUrlOrWarn(_launcher, url);

    [RelayCommand]
    private async Task CheckForUpdatesAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var result = await _updateChecker.CheckForUpdateAsync(cancellationToken);
            if (result.HasUpdate)
            {
                await HandleUpdateResultAsync(result, cancellationToken);
            }
            else
            {
                _ui.Notify($"目前已是最新版本（v{result.CurrentVersion}）", NotificationType.Info);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("檢查更新已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "檢查更新失敗");
            _ui.Notify($"檢查更新失敗：{ex.Message}", NotificationType.Error);
        }
    }

    /// <summary>啟動時依設定自動檢查更新，有新版本時詢問使用者</summary>
    public async Task CheckForUpdateOnStartupAsync(CancellationToken cancellationToken = default)
    {
        if (!IsAutoUpdateEnabled)
        {
            return;
        }

        try
        {
            UpdateCheckResult result = await _updateChecker.CheckForUpdateAsync(cancellationToken);
            if (result.HasUpdate)
            {
                await HandleUpdateResultAsync(result, cancellationToken);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("啟動自動檢查更新已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "啟動自動檢查更新失敗");
        }
    }

    /// <summary>處理檢查更新結果：提示使用者更新，確認後下載驗證、停止伺服器、置換執行檔並重新啟動；同時僅允許一個更新流程</summary>
    public async Task HandleUpdateResultAsync(UpdateCheckResult result, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(result);
        if (Interlocked.Exchange(ref _updateInProgress, 1) == 1)
        {
            Logger.Information("更新流程進行中，忽略重複要求");
            return;
        }

        try
        {
            await RunUpdateAsync(result, cancellationToken);
        }
        finally
        {
            Volatile.Write(ref _updateInProgress, 0);
        }
    }

    private async Task RunUpdateAsync(UpdateCheckResult result, CancellationToken cancellationToken)
    {
        string cleanedNotes = CleanReleaseNotes(result.ReleaseNotes);
        bool confirm = await _ui.ConfirmAsync(
            $"發現新版本 {result.LatestVersion}（目前版本：{result.CurrentVersion}）！\n\n更新內容：\n{cleanedNotes}\n\n是否立即更新主程式？",
            "發現新版本",
            UiMessageLevel.Question);

        if (!confirm)
        {
            // 否：本次取消，下次重新啟動時仍會再次詢問
            return;
        }

        if (string.IsNullOrWhiteSpace(result.DownloadUrl))
        {
            bool openWeb = await _ui.ConfirmAsync(
                "目前發布版本不支援直接自動安裝，是否前往 GitHub 發布頁面手動下載？",
                "手動下載更新",
                UiMessageLevel.Information);
            if (openWeb)
            {
                OpenUrl(result.ReleasePageUrl);
            }

            return;
        }

        try
        {
            string installerPath;
            using (var progressDialog = _ui.ShowOperationProgress("主程式自動更新", "準備下載更新檔案..."))
            {
                var progress = progressDialog.CreateProgress();

                installerPath = await _appUpdateService.DownloadAndVerifyUpdateAsync(result, progress, cancellationToken);

                progressDialog.UpdateProgress(100, 100, "更新檔案驗證成功，即將停止伺服器並套用更新...");
            }

            if (!await _stopCoordinator.StopAllForShutdownAsync())
            {
                _ui.Notify("已取消更新：伺服器仍在執行中", NotificationType.Info);
                return;
            }

            // 套用更新前先寫入防抖中的設定，檔案置換於背景執行緒；啟動新版前釋放單一執行個體鎖，失敗時取回
            await FlushPendingSaveAsync();
            await Task.Run(() => _appUpdateService.ApplyUpdateAndRestart(installerPath, _ui.LaunchReplacementInstance), cancellationToken);
            _ui.ShutdownApplication(0);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("使用者取消主程式更新");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "主程式更新流程失敗");
            bool fallback = await _ui.ConfirmAsync(
                $"更新主程式失敗：{ex.Message}\n\n是否改為前往 GitHub 手動下載最新版本？",
                "更新失敗",
                UiMessageLevel.Error);
            if (fallback)
            {
                OpenUrl(result.ReleasePageUrl);
            }
        }
    }

    public static string CleanReleaseNotes(string? notes)
    {
        if (string.IsNullOrWhiteSpace(notes))
        {
            return "（無更新紀錄）";
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
            return "（無更新紀錄）";
        }

        var trimmedLines = keptLines.GetRange(start, Math.Min(end - start + 1, 15));
        if (end - start + 1 > 15)
        {
            trimmedLines.Add("...（完整內容請檢視發行頁面）");
        }

        return string.Join(Environment.NewLine, trimmedLines);
    }

    [RelayCommand]
    private async Task ResetToDefaultSizeAsync()
    {
        if (await _ui.ConfirmAsync("確定要將主視窗大小與位置重設為預設值嗎？", "確認重設視窗大小"))
        {
            _onResetWindowSizeRequested();
        }
    }

    [RelayCommand]
    private async Task ResetAllSettingsAsync()
    {
        if (!await _ui.ConfirmAsync("確定要將所有偏好設定還原為原廠預設值嗎？", "確認還原預設", UiMessageLevel.Warning))
        {
            return;
        }

        // 批次還原全部欄位後一次寫檔並套用主題
        _suppressSave = true;
        try
        {
            IsAutoUpdateEnabled = true;
            IsAutoBackupBeforeStartEnabled = false;
            BackupRetentionCount = ServerDefaults.DefaultBackupRetentionCount;
            SelectedThemeModeIndex = 0;
            ApplyAccentState(null, _accentColorService.GetSystemAccentColor());
        }
        finally
        {
            _suppressSave = false;
        }

        await SaveNowAsync();
        _accentColorService.ApplyAccentColor(null);
        _onThemeModeChanged(SelectedThemeMode);
        _onResetWindowSizeRequested();
    }

    public void SelectAccentColor(Windows.UI.Color color)
    {
        string hex = AccentColorService.ToHex(color);
        ApplyAccentState(hex, color);
        ScheduleSave();
        _accentColorService.ApplyAccentColor(hex);
    }

    [RelayCommand(CanExecute = nameof(IsCustomAccentColor))]
    public void ResetAccentColor()
    {
        ApplyAccentState(null, _accentColorService.GetSystemAccentColor());
        ScheduleSave();
        _accentColorService.ApplyAccentColor(null);
    }

    /// <summary>未使用自訂色時，系統強調色變更即同步顯示</summary>
    private void OnAccentColorChanged()
    {
        if (!_disposed && !IsCustomAccentColor)
        {
            CurrentAccentColor = _accentColorService.GetSystemAccentColor();
        }
    }

    /// <summary>重新計時防抖寫檔</summary>
    private void ScheduleSave()
    {
        if (_suppressSave || _disposed)
        {
            return;
        }

        _savePending = true;
        _saveTimer.StopTimer();
        _saveTimer.StartTimer();
    }

    /// <summary>立即寫入尚未儲存的變更；關閉應用程式前由頁面處置流程呼叫</summary>
    public async Task FlushPendingSaveAsync()
    {
        _saveTimer.StopTimer();
        if (_savePending)
        {
            await SaveNowAsync();
        }
    }

    /// <summary>於 UI 執行緒擷取欄位快照，背景執行緒一次寫入全部偏好設定；失敗時記錄並通知</summary>
    private async Task SaveNowAsync()
    {
        _saveTimer.StopTimer();
        _savePending = false;
        var preferences = new UserPreferences(
            IsAutoUpdateEnabled,
            IsAutoBackupBeforeStartEnabled,
            (int)BackupRetentionCount,
            SelectedThemeMode,
            CustomAccentColor);
        await _saveGate.WaitAsync();
        try
        {
            await Task.Run(() => _settingsManager.SetPreferences(preferences));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Error(ex, "儲存設定失敗");
            _ui.Notify($"儲存設定失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            _saveGate.Release();
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _accentColorService.AccentColorChanged -= OnAccentColorChanged;
        _saveTimer.Dispose();
    }

    /// <summary>更新強調色顯示狀態；hex 為 null 表示使用系統色</summary>
    private void ApplyAccentState(string? hex, Windows.UI.Color color)
    {
        CustomAccentColor = hex;
        CurrentAccentColor = color;
        IsCustomAccentColor = hex is not null;
        AccentColorSummaryText = hex is null ? "使用 Windows 系統強調色（預設）" : $"自訂顏色：{hex}";
    }
}
