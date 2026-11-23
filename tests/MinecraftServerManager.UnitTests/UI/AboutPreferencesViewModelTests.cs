using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class AboutPreferencesViewModelTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm_test_");
    private readonly string _testDir;

    public AboutPreferencesViewModelTests()
    {
        _testDir = _testDirTemp.FullName;
    }

    public void Dispose() => _testDirTemp.Dispose();

    private AboutPreferencesViewModel Create(IUiService uiService, SettingsManager? settings = null, IUpdateCheckerService? updateChecker = null, IAppUpdateService? appUpdateService = null, Action? onResetWindowSizeRequested = null, IExternalLauncher? launcher = null) =>
        new(uiService, settings ?? new SettingsManager(_testDir), new ServerStopCoordinator(uiService, NoOp.Create<IServerRuntimeHost>()), updateChecker ?? NoOp.Create<IUpdateCheckerService>(), static _ => { }, onResetWindowSizeRequested ?? (static () => { }), launcher ?? NoOp.Create<IExternalLauncher>(), appUpdateService ?? NoOp.Create<IAppUpdateService>(), NoOp.Create<IAccentColorService>());

    [Fact]
    public void OpenLicense_Invoked_OpensGplV3Text()
    {
        var launcher = new RecordingLauncher();
        var vm = Create(new NoOpUiService(), launcher: launcher);

        vm.OpenLicenseCommand.Execute(null);

        Assert.Equal(AppInfo.LicenseUrl, Assert.Single(launcher.OpenedUrls));
        Assert.Equal("https://www.gnu.org/licenses/gpl-3.0.html", AppInfo.LicenseUrl);
    }

    [Theory]
    [InlineData(1.0, "目前螢幕解析度：1920 × 1080")]
    [InlineData(1.5, "目前螢幕解析度：1920 × 1080（縮放 150%）")]
    public void UpdateWindowMetrics_NewMetrics_ShowsSizesAndScale(double scale, string expectedScreen)
    {
        var vm = Create(new NoOpUiService());

        vm.UpdateWindowMetrics(new WindowMetrics(1280, 720, 1920, 1080, scale));

        Assert.Equal(expectedScreen, vm.ScreenResolutionInfo);
        Assert.Equal("目前主視窗大小：1280 × 720", vm.CurrentWindowSizeInfo);

        vm.UpdateWindowMetrics(new WindowMetrics(1500, 900, 1920, 1080, scale));
        Assert.Equal("目前主視窗大小：1500 × 900", vm.CurrentWindowSizeInfo);
    }

    [Fact]
    public void Constructor_Default_AlignsWithAppInfo()
    {
        Assert.Equal(AppInfo.Version, AboutPreferencesViewModel.AppVersion);
        Assert.Equal(AppInfo.AppName, AboutPreferencesViewModel.AppDescription);
        Assert.Equal(AppInfo.Author, AboutPreferencesViewModel.AppAuthor);
    }

    [Fact]
    public void ManualCheckVisibility_AutoUpdateToggled_IsInverted()
    {
        var vm = Create(NoOpUiService.Instance);
        vm.IsAutoUpdateEnabled = true;
        Assert.False(vm.IsManualCheckVisible);

        vm.IsAutoUpdateEnabled = false;
        Assert.True(vm.IsManualCheckVisible);
    }

    [Fact]
    public async Task ResetAllSettings_Confirmed_RestoresDefaults()
    {
        var settings = new SettingsManager(_testDir);
        bool windowSizeResetCalled = false;
        var ui = new ManualUiService();
        var vm = Create(
            ui,
            settings,
            onResetWindowSizeRequested: () => windowSizeResetCalled = true);
        vm.IsAutoUpdateEnabled = false;
        vm.SelectedThemeModeIndex = 1; // 淺色

        await vm.ResetAllSettingsCommand.ExecuteAsync(null);

        Assert.True(vm.IsAutoUpdateEnabled);
        Assert.Equal(0, vm.SelectedThemeModeIndex);
        Assert.True(windowSizeResetCalled);
        Assert.Empty(ui.Notifications);
    }

    [Fact]
    public async Task SelectAccentColor_NewColor_UpdatesSettings()
    {
        var settings = new SettingsManager(_testDir);
        var vm = Create(NoOpUiService.Instance, settings);

        var customColor = Windows.UI.Color.FromArgb(255, 18, 52, 86);
        vm.SelectAccentColor(customColor);
        await vm.FlushPendingSaveAsync();

        Assert.True(vm.IsCustomAccentColor);
        Assert.Equal("#123456", vm.CustomAccentColor);
        Assert.Equal("#123456", settings.GetCustomAccentColor());

        vm.ResetAccentColor();
        await vm.FlushPendingSaveAsync();
        Assert.False(vm.IsCustomAccentColor);
        Assert.Null(vm.CustomAccentColor);
        Assert.Null(settings.GetCustomAccentColor());
    }

    [Fact]
    public async Task CheckForUpdates_AlreadyLatest_Notifies()
    {
        var ui = new ManualUiService();
        var mockChecker = new MockUpdateChecker(TestUpdateResults.Create(
            hasUpdate: false,
            currentVersion: "2.1.0",
            latestVersion: "2.1.0",
            releaseTitle: "v2.1.0",
            releaseNotes: "無更新",
            downloadUrl: null,
            sha256ChecksumUrl: null));

        var vm = Create(
            ui,
            updateChecker: mockChecker);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.Contains(ui.Notifications, static n => n.Message.Contains("目前已是最新版本", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task CheckForUpdates_UserConfirmation_DownloadsAndAppliesOnlyWhenConfirmed(bool userConfirmed)
    {
        var mockChecker = new MockUpdateChecker(TestUpdateResults.Create(
            currentVersion: "2.1.0",
            latestVersion: "2.2.0",
            releaseTitle: "v2.2.0",
            downloadUrl: "https://example.com/update.exe",
            sha256ChecksumUrl: null));
        var mockUpdateService = new MockAppUpdateService();
        var fakeUi = new ManualUiService { ConfirmResult = userConfirmed };

        var vm = Create(
            fakeUi,
            updateChecker: mockChecker,
            appUpdateService: mockUpdateService);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.Equal(userConfirmed, mockUpdateService.DownloadInvoked);
        Assert.Equal(userConfirmed, mockUpdateService.ApplyInvoked);
    }

    [Fact]
    public async Task ResetAccentColor_CustomColor_AppliesSystemDefault()
    {
        var settings = new SettingsManager(_testDir);
        settings.UpdatePreferences(p => p with { CustomAccentColor = "#112233" });
        var vm = Create(NoOpUiService.Instance, settings);

        vm.ResetAccentColor();
        await vm.FlushPendingSaveAsync();
        vm.Dispose();

        Assert.False(vm.IsCustomAccentColor);
        Assert.Null(vm.CustomAccentColor);
        Assert.Null(settings.Snapshot.WindowPreferences.CustomAccentColor);
    }

    private sealed class MockAppUpdateService : IAppUpdateService
    {
        public bool DownloadInvoked { get; private set; }
        public bool ApplyInvoked { get; private set; }

        public Task<string> DownloadAndVerifyUpdateAsync(
            UpdateCheckResult update,
            IProgress<(int Percentage, string StatusMessage)>? progress = null,
            CancellationToken cancellationToken = default)
        {
            DownloadInvoked = true;
            return Task.FromResult("C:\\fake\\path.exe");
        }

        public void ApplyUpdateAndRestart(string verifiedInstallerPath, Action<Action> launchReplacement) => ApplyInvoked = true;

        public void CleanupPreviousUpdateBackup()
        {
        }
    }

    private sealed class MockUpdateChecker(UpdateCheckResult result) : IUpdateCheckerService
    {
        public Task<UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(result);
    }

    [Fact]
    public async Task BackupSettings_Changed_WritesSettings()
    {
        var settings = new SettingsManager(_testDir);
        var vm = Create(new NoOpUiService(), settings);
        Assert.False(vm.IsAutoBackupBeforeStartEnabled);
        Assert.Equal(10, vm.BackupRetentionCount);

        vm.IsAutoBackupBeforeStartEnabled = true;
        vm.BackupRetentionCount = 7;
        await vm.FlushPendingSaveAsync();
        vm.Dispose();

        Assert.True(settings.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(7, settings.GetBackupRetentionCount());
    }

    [Fact]
    public async Task Constructor_Default_DoesNotWriteSettings()
    {
        var settings = new CountingSettings(new SettingsManager(_testDir));

        using var vm = new AboutPreferencesViewModel(new NoOpUiService(), settings, new ServerStopCoordinator(NoOpUiService.Instance, NoOp.Create<IServerRuntimeHost>()), NoOp.Create<IUpdateCheckerService>(), static _ => { }, static () => { }, NoOp.Create<IExternalLauncher>(), NoOp.Create<IAppUpdateService>(), NoOp.Create<IAccentColorService>());
        await vm.FlushPendingSaveAsync();

        Assert.Equal(0, settings.SaveCount);
    }

    [Fact]
    public async Task ResetAllSettings_Confirmed_WritesOnce()
    {
        var inner = new SettingsManager(_testDir);
        var settings = new CountingSettings(inner);
        using var vm = new AboutPreferencesViewModel(new NoOpUiService(), settings, new ServerStopCoordinator(NoOpUiService.Instance, NoOp.Create<IServerRuntimeHost>()), NoOp.Create<IUpdateCheckerService>(), static _ => { }, static () => { }, NoOp.Create<IExternalLauncher>(), NoOp.Create<IAppUpdateService>(), NoOp.Create<IAccentColorService>());

        await vm.ResetAllSettingsCommand.ExecuteAsync(null);
        await vm.FlushPendingSaveAsync();

        Assert.Equal(1, settings.SaveCount);
    }

    [Fact]
    public void OpenGithub_LaunchFailure_NotifiesWarning()
    {
        var ui = new ManualUiService();
        var vm = Create(ui, launcher: NoOp.Create<IExternalLauncher>());

        vm.OpenGithubCommand.Execute(null);

        Assert.Contains(ui.Notifications, static n => n.Type == NotificationType.Warning);
    }

    [Fact]
    public async Task HandleUpdateResult_ConcurrentCall_IsIgnored()
    {
        var gate = new TaskCompletionSource<bool>();
        var ui = new GatedConfirmUiService(gate.Task);
        var update = new MockAppUpdateService();
        var vm = Create(ui, appUpdateService: update);
        var result = new UpdateCheckResult(true, "2.1.0", "2.2.0", "v2.2.0", "測試", "https://example.com/u.exe", null, "https://example.com");

        Task first = vm.HandleUpdateResultAsync(result, TestContext.Current.CancellationToken);
        await vm.HandleUpdateResultAsync(result, TestContext.Current.CancellationToken);
        gate.SetResult(false);
        await first;

        Assert.Equal(1, ui.ConfirmCount);
    }

    private sealed class GatedConfirmUiService(Task<bool> gate) : NoOpUiService
    {
        public int ConfirmCount { get; private set; }

        public override Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question)
        {
            ConfirmCount++;
            return gate;
        }
    }

    private sealed class CountingSettings(SettingsManager inner) : ISettingsManager
    {
        public int SaveCount { get; private set; }

        public string GetServersRoot() => inner.GetServersRoot();

        public void SetServersRoot(string? path) => inner.SetServersRoot(path);

        public void SetExactServersRoot(string? path) => inner.SetExactServersRoot(path);

        public string GetValidatedServersRootPath(bool create = false) => inner.GetValidatedServersRootPath(create);

        public bool IsAutoUpdateEnabled() => inner.IsAutoUpdateEnabled();

        public bool IsAutoBackupBeforeStartEnabled() => inner.IsAutoBackupBeforeStartEnabled();

        public int GetBackupRetentionCount() => inner.GetBackupRetentionCount();

        public MainWindowSettings GetMainWindowSettings() => inner.GetMainWindowSettings();

        public void SetMainWindowSettings(int width, int height, int? x = null, int? y = null, bool maximized = false) => inner.SetMainWindowSettings(width, height, x, y, maximized);

        public string GetThemeMode() => inner.GetThemeMode();

        public string? GetCustomAccentColor() => inner.GetCustomAccentColor();

        public void SetPreferences(UserPreferences preferences)
        {
            SaveCount++;
            inner.SetPreferences(preferences);
        }
    }

    [Fact]
    public void BackupRetentionCount_NaN_RestoresCurrentSetting()
    {
        var settings = new SettingsManager(_testDir);
        settings.UpdatePreferences(p => p with { BackupRetentionCount = 5 });
        var vm = Create(new NoOpUiService(), settings);

        vm.BackupRetentionCount = double.NaN;

        Assert.Equal(5, vm.BackupRetentionCount);
        Assert.Equal(5, settings.GetBackupRetentionCount());
    }

    [Fact]
    public async Task BackupRetentionCount_OutOfRange_Clamps()
    {
        var settings = new SettingsManager(_testDir);
        var vm = Create(new NoOpUiService(), settings);

        vm.BackupRetentionCount = 999;
        await vm.FlushPendingSaveAsync();

        Assert.Equal(100, vm.BackupRetentionCount);
        Assert.Equal(100, settings.GetBackupRetentionCount());
    }

    [Fact]
    public async Task ResetAllSettings_Confirmed_RestoresBackupDefaults()
    {
        var settings = new SettingsManager(_testDir);
        settings.UpdatePreferences(p => p with { AutoBackupBeforeStart = true });
        settings.UpdatePreferences(p => p with { BackupRetentionCount = 3 });
        var vm = Create(new NoOpUiService(), settings);

        await vm.ResetAllSettingsCommand.ExecuteAsync(null);

        Assert.False(settings.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(10, settings.GetBackupRetentionCount());
    }
}
