using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed partial class AboutPreferencesViewModelTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AboutPreferencesViewModelTests));
    private readonly string _testDir;

    public AboutPreferencesViewModelTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_test_" + Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testDir))
            {
                Directory.Delete(_testDir, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    private AboutPreferencesViewModel Create(IUiService uiService, SettingsManager? settings = null, IUpdateCheckerService? updateChecker = null, IAppUpdateService? appUpdateService = null, Action? onResetWindowSizeRequested = null) =>
        new(uiService, settings ?? new SettingsManager(_testDir), updateChecker ?? NoOp.Create<IUpdateCheckerService>(), static _ => { }, onResetWindowSizeRequested ?? (static () => { }), NoOp.Create<IExternalLauncher>(), appUpdateService ?? NoOp.Create<IAppUpdateService>());

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
        var fakeUi = new ConfirmingUiService(confirmResult: false);

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
        var fakeUi = new ConfirmingUiService(confirmResult: true);

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

    private sealed class ConfirmingUiService(bool confirmResult) : NoOpUiService
    {
        public override Task<bool> ConfirmAsync(string message, string title, UiMessageLevel level = UiMessageLevel.Question) =>
            Task.FromResult(confirmResult);
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
}
