using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed partial class AboutPreferencesViewModelTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm_test_");
    private readonly string _testDir;

    public AboutPreferencesViewModelTests()
    {
        _testDir = _testDirTemp.FullName;
    }

    public void Dispose() => _testDirTemp.Dispose();

    private AboutPreferencesViewModel Create(IUiService uiService, SettingsManager? settings = null, IUpdateCheckerService? updateChecker = null, IAppUpdateService? appUpdateService = null, Action? onResetWindowSizeRequested = null) =>
        new(uiService, settings ?? new SettingsManager(_testDir), updateChecker ?? NoOp.Create<IUpdateCheckerService>(), static _ => { }, onResetWindowSizeRequested ?? (static () => { }), NoOp.Create<IExternalLauncher>(), appUpdateService ?? NoOp.Create<IAppUpdateService>());

    [Fact]
    public void OpenLicense_OpensGplV3FullText()
    {
        var launcher = new RecordingLauncher();
        var vm = new AboutPreferencesViewModel(new NoOpUiService(), new SettingsManager(_testDir), NoOp.Create<IUpdateCheckerService>(), static _ => { }, static () => { }, launcher, NoOp.Create<IAppUpdateService>());

        vm.OpenLicenseCommand.Execute(null);

        Assert.Equal(AppInfo.LicenseUrl, Assert.Single(launcher.OpenedUrls));
        Assert.Equal("https://www.gnu.org/licenses/gpl-3.0.html", AppInfo.LicenseUrl);
    }

    [Theory]
    [InlineData(1.0, "目前螢幕解析度：1920 × 1080")]
    [InlineData(1.5, "目前螢幕解析度：1920 × 1080（縮放 150%）")]
    public void UpdateWindowMetrics_ShowsCurrentSizesAndScale(double scale, string expectedScreen)
    {
        var vm = Create(new NoOpUiService());

        vm.UpdateWindowMetrics(new WindowMetrics(1280, 720, 1920, 1080, scale));

        Assert.Equal(expectedScreen, vm.ScreenResolutionInfo);
        Assert.Equal("目前主視窗大小：1280 × 720", vm.CurrentWindowSizeInfo);

        vm.UpdateWindowMetrics(new WindowMetrics(1500, 900, 1920, 1080, scale));
        Assert.Equal("目前主視窗大小：1500 × 900", vm.CurrentWindowSizeInfo);
    }

    [Fact]
    public void ShouldAlignWithAppInfo()
    {
        Assert.Equal(AppInfo.Version, AboutPreferencesViewModel.AppVersion);
        Assert.Equal(AppInfo.AppName, AboutPreferencesViewModel.AppDescription);
        Assert.Equal(AppInfo.Author, AboutPreferencesViewModel.AppAuthor);
    }

    [Fact]
    public void ManualCheckVisibilityShouldBeInvertedFromAutoUpdate()
    {
        var vm = Create(NoOpUiService.Instance);
        vm.IsAutoUpdateEnabled = true;
        Assert.False(vm.IsManualCheckVisible);

        vm.IsAutoUpdateEnabled = false;
        Assert.True(vm.IsManualCheckVisible);
    }

    [Fact]
    public void ResetAllSettingsShouldRestoreDefaults()
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

        vm.ResetAllSettingsCommand.Execute(null);

        Assert.True(vm.IsAutoUpdateEnabled);
        Assert.Equal(0, vm.SelectedThemeModeIndex);
        Assert.True(windowSizeResetCalled);
        Assert.Empty(ui.Notifications);
    }

    [Fact]
    public void SelectAccentColorShouldUpdateSettingsAndViewModel()
    {
        var settings = new SettingsManager(_testDir);
        var vm = Create(NoOpUiService.Instance, settings);

        var customColor = Windows.UI.Color.FromArgb(255, 18, 52, 86);
        vm.SelectAccentColor(customColor);

        Assert.True(vm.IsCustomAccentColor);
        Assert.Equal("#123456", vm.CustomAccentColor);
        Assert.Equal("#123456", settings.GetCustomAccentColor());

        vm.ResetAccentColor();
        Assert.False(vm.IsCustomAccentColor);
        Assert.Null(vm.CustomAccentColor);
        Assert.Null(settings.GetCustomAccentColor());
    }

    [Fact]
    public void AccentColorService_ParseAndFormatHex_ShouldRoundTripCorrectly()
    {
        var parsed = AccentColorService.ParseColor("#3A7BD5");
        Assert.NotNull(parsed);
        Assert.Equal(255, parsed.Value.A);
        Assert.Equal(0x3A, parsed.Value.R);
        Assert.Equal(0x7B, parsed.Value.G);
        Assert.Equal(0xD5, parsed.Value.B);
        Assert.Equal("#3A7BD5", AccentColorService.ToHex(parsed.Value));

        Assert.Null(AccentColorService.ParseColor(null));
        Assert.Null(AccentColorService.ParseColor(""));
        Assert.Null(AccentColorService.ParseColor("#ZZZZZZ"));
    }

    [Fact]
    public async Task CheckForUpdatesShouldNotifyWhenAlreadyLatestVersion()
    {
        var ui = new ManualUiService();
        var mockChecker = new MockUpdateChecker(new UpdateCheckResult(
            HasUpdate: false,
            CurrentVersion: "2.1.0",
            LatestVersion: "2.1.0",
            ReleaseTitle: "v2.1.0",
            ReleaseNotes: "無更新",
            DownloadUrl: null,
            Sha256ChecksumUrl: null,
            ReleasePageUrl: "https://example.com"));

        var vm = Create(
            ui,
            updateChecker: mockChecker);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.Contains(ui.Notifications, static n => n.Message.Contains("目前已是最新版本", StringComparison.Ordinal));
    }

    [Fact]
    public async Task CheckForUpdates_WhenUserDeclinesUpdate_DoesNotDownloadOrApply()
    {
        var mockChecker = new MockUpdateChecker(new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.1.0",
            LatestVersion: "2.2.0",
            ReleaseTitle: "v2.2.0",
            ReleaseNotes: "測試更新",
            DownloadUrl: "https://example.com/update.exe",
            Sha256ChecksumUrl: null,
            ReleasePageUrl: "https://example.com"));
        var mockUpdateService = new MockAppUpdateService();
        var fakeUi = new ManualUiService { ConfirmResult = false };

        var vm = Create(
            fakeUi,
            updateChecker: mockChecker,
            appUpdateService: mockUpdateService);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.False(mockUpdateService.DownloadInvoked);
        Assert.False(mockUpdateService.ApplyInvoked);
    }

    [Fact]
    public async Task CheckForUpdates_WhenUserConfirmsUpdate_DownloadsAndAppliesUpdate()
    {
        var mockChecker = new MockUpdateChecker(new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.1.0",
            LatestVersion: "2.2.0",
            ReleaseTitle: "v2.2.0",
            ReleaseNotes: "測試更新",
            DownloadUrl: "https://example.com/update.exe",
            Sha256ChecksumUrl: null,
            ReleasePageUrl: "https://example.com"));
        var mockUpdateService = new MockAppUpdateService();
        var fakeUi = new ManualUiService { ConfirmResult = true };

        var vm = Create(
            fakeUi,
            updateChecker: mockChecker,
            appUpdateService: mockUpdateService);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.True(mockUpdateService.DownloadInvoked);
        Assert.True(mockUpdateService.ApplyInvoked);
    }

    [Fact]
    public void AccentColorService_ApplyAndReset_FiresAccentColorChanged()
    {
        bool eventFired = false;
        Action handler = () => eventFired = true;
        AccentColorService.AccentColorChanged += handler;
        try
        {
            AccentColorService.ApplyAccentColor("#FF112233");
            Assert.True(eventFired);

            eventFired = false;
            AccentColorService.ApplyAccentColor(null);
            Assert.True(eventFired);
        }
        finally
        {
            AccentColorService.AccentColorChanged -= handler;
        }
    }

    [Fact]
    public void ResetAccentColor_ResetsCustomColorAndAppliesSystemDefault()
    {
        var settings = new SettingsManager(_testDir);
        settings.SetCustomAccentColor("#112233");
        var vm = Create(NoOpUiService.Instance, settings);

        vm.ResetAccentColor();

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

        public void ApplyUpdateAndRestart(string verifiedInstallerPath) => ApplyInvoked = true;
    }

    private sealed class MockUpdateChecker(UpdateCheckResult result) : IUpdateCheckerService
    {
        public Task<UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(result);
    }

    [Fact]
    public void BackupSettings_LoadFromAndWriteToSettings()
    {
        var settings = new SettingsManager(_testDir);
        var vm = Create(new NoOpUiService(), settings);
        Assert.False(vm.IsAutoBackupBeforeStartEnabled);
        Assert.Equal(10, vm.BackupRetentionCount);

        vm.IsAutoBackupBeforeStartEnabled = true;
        vm.BackupRetentionCount = 7;

        Assert.True(settings.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(7, settings.GetBackupRetentionCount());
    }

    [Fact]
    public void BackupRetentionCount_NaN_RestoresCurrentSetting()
    {
        var settings = new SettingsManager(_testDir);
        settings.SetBackupRetentionCount(5);
        var vm = Create(new NoOpUiService(), settings);

        vm.BackupRetentionCount = double.NaN;

        Assert.Equal(5, vm.BackupRetentionCount);
        Assert.Equal(5, settings.GetBackupRetentionCount());
    }

    [Fact]
    public void BackupRetentionCount_OutOfRangeIsClamped()
    {
        var settings = new SettingsManager(_testDir);
        var vm = Create(new NoOpUiService(), settings);

        vm.BackupRetentionCount = 999;

        Assert.Equal(100, vm.BackupRetentionCount);
        Assert.Equal(100, settings.GetBackupRetentionCount());
    }

    [Fact]
    public async Task ResetAllSettings_RestoresBackupDefaults()
    {
        var settings = new SettingsManager(_testDir);
        settings.SetAutoBackupBeforeStartEnabled(true);
        settings.SetBackupRetentionCount(3);
        var vm = Create(new NoOpUiService(), settings);

        await vm.ResetAllSettingsCommand.ExecuteAsync(null);

        Assert.False(settings.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(10, settings.GetBackupRetentionCount());
    }
}
