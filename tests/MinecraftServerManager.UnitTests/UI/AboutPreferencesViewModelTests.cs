using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class AboutPreferencesViewModelTests : IDisposable
{
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
        catch
        {
        }
    }

    [Fact]
    public void ShouldAlignWithAppInfoVersion2AndGpl3()
    {
        var vm = new AboutPreferencesViewModel();

        Assert.Equal("about_preferences", vm.Key);
        Assert.Equal("關於與設定", vm.Title);
        Assert.Equal("Minecraft Server Manager", AboutPreferencesViewModel.AppName);
        Assert.Equal("2.0.0", AboutPreferencesViewModel.AppVersion);
        Assert.Equal("Minecraft 伺服器管理器", AboutPreferencesViewModel.AppDescription);
        Assert.Equal("Colin955023", AboutPreferencesViewModel.Developer);
        Assert.Equal("Colin955023", vm.GithubOwner);
        Assert.Equal("MinecraftServerManager", vm.GithubRepo);
        Assert.Equal("https://github.com/Colin955023/MinecraftServerManager", AboutPreferencesViewModel.GithubUrl);
        Assert.Equal(".NET 10 (WPF)", AboutPreferencesViewModel.TargetFramework);
        Assert.Equal("GNU General Public License v3.0 (GPL-3.0)", AboutPreferencesViewModel.License);
    }

    [Fact]
    public void ManualCheckVisibilityShouldBeInvertedFromAutoUpdate()
    {
        var vm = new AboutPreferencesViewModel
        {
            IsAutoUpdateEnabled = true
        };
        Assert.False(vm.IsManualCheckVisible);

        vm.IsAutoUpdateEnabled = false;
        Assert.True(vm.IsManualCheckVisible);
    }

    [Fact]
    public void ResetAllSettingsShouldRestoreDefaults()
    {
        var settings = new Infrastructure.Settings.SettingsManager(_testDir);
        bool windowSizeResetCalled = false;
        var vm = new AboutPreferencesViewModel(
            settingsManager: settings,
            onResetWindowSizeRequested: () => windowSizeResetCalled = true)
        {
            IsAutoUpdateEnabled = false,
            SelectedThemeModeIndex = 1 // 淺色
        };

        vm.ResetAllSettingsCommand.Execute(null);

        Assert.True(vm.IsAutoUpdateEnabled);
        Assert.Equal(0, vm.SelectedThemeModeIndex);
        Assert.True(windowSizeResetCalled);
    }

    [Fact]
    public void UiScaleChangesShouldApplyImmediatelyWithoutApplyButton()
    {
        var settings = new Infrastructure.Settings.SettingsManager(_testDir);
        double invokedScale = 0;
        var vm = new AboutPreferencesViewModel(
            settingsManager: settings,
            onUiScaleChanged: scale => invokedScale = scale)
        {
            // 切換到 125% (索引 2)
            SelectedUiScaleIndex = 2
        };

        Assert.Equal(1.25, settings.GetUiScale());
        Assert.Equal(1.25, invokedScale);
    }

    [Fact]
    public async Task CheckForUpdatesShouldNotifyWhenAlreadyLatestVersion()
    {
        string notification = string.Empty;
        var mockChecker = new MockUpdateChecker(new Core.Ports.UpdateCheckResult(
            HasUpdate: false,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.0",
            ReleaseTitle: "2.0.0",
            ReleaseNotes: "無更新",
            DownloadUrl: null,
            Sha256ChecksumUrl: null,
            ReleasePageUrl: "https://example.com"));

        var vm = new AboutPreferencesViewModel(
            updateChecker: mockChecker,
            notificationSink: (msg, isErr) => notification = msg);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.Contains("目前已是最新版本", notification);
    }

    [Fact]
    public async Task CheckForUpdates_WhenUserDeclinesUpdate_DoesNotDownloadOrApply()
    {
        var mockChecker = new MockUpdateChecker(new Core.Ports.UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "更新說明",
            DownloadUrl: "https://example.com/msm.exe",
            Sha256ChecksumUrl: "https://example.com/msm.exe.sha256",
            ReleasePageUrl: "https://example.com"));

        var mockUpdateService = new MockAppUpdateService();
        var mockUi = new ConfirmingUiService(confirmResult: false);

        var vm = new AboutPreferencesViewModel(
            updateChecker: mockChecker,
            uiService: mockUi,
            appUpdateService: mockUpdateService);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.False(mockUpdateService.DownloadInvoked);
        Assert.False(mockUpdateService.ApplyInvoked);
    }

    [Fact]
    public async Task CheckForUpdates_WhenUserConfirmsUpdate_DownloadsAndAppliesUpdate()
    {
        var mockChecker = new MockUpdateChecker(new Core.Ports.UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "更新說明",
            DownloadUrl: "https://example.com/msm.exe",
            Sha256ChecksumUrl: "https://example.com/msm.exe.sha256",
            ReleasePageUrl: "https://example.com"));

        var mockUpdateService = new MockAppUpdateService();
        var mockUi = new ConfirmingUiService(confirmResult: true);

        var vm = new AboutPreferencesViewModel(
            updateChecker: mockChecker,
            uiService: mockUi,
            appUpdateService: mockUpdateService);

        await vm.CheckForUpdatesCommand.ExecuteAsync(null);

        Assert.True(mockUpdateService.DownloadInvoked);
        Assert.True(mockUpdateService.ApplyInvoked);
    }

    private sealed class ConfirmingUiService(bool confirmResult) : NoOpUiService
    {
        public override bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question) =>
            confirmResult;
    }

    private sealed class MockAppUpdateService : Core.Ports.IAppUpdateService
    {
        public bool DownloadInvoked { get; private set; }
        public bool ApplyInvoked { get; private set; }

        public Task<string> DownloadAndVerifyUpdateAsync(
            Core.Ports.UpdateCheckResult update,
            IProgress<(int Percentage, string StatusMessage)>? progress = null,
            CancellationToken cancellationToken = default)
        {
            DownloadInvoked = true;
            return Task.FromResult("C:\\fake\\path.exe");
        }

        public void ApplyUpdateAndRestart(string verifiedInstallerPath) => ApplyInvoked = true;
    }

    private sealed class MockUpdateChecker(Core.Ports.UpdateCheckResult result) : Core.Ports.IUpdateCheckerService
    {
        public Task<Core.Ports.UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(result);
    }
}
