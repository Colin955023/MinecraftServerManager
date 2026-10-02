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
        Assert.Equal("Minecraft Server Manager", vm.AppName);
        Assert.Equal("2.0.0", vm.AppVersion);
        Assert.Equal("Minecraft 伺服器管理器", vm.AppDescription);
        Assert.Equal("Colin955023", vm.Developer);
        Assert.Equal("Colin955023", vm.GithubOwner);
        Assert.Equal("MinecraftServerManager", vm.GithubRepo);
        Assert.Equal("https://github.com/Colin955023/MinecraftServerManager", vm.GithubUrl);
        Assert.Equal(".NET 10 (WPF)", vm.TargetFramework);
        Assert.Equal("GNU General Public License v3.0 (GPL-3.0)", vm.License);
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
        var vm = new AboutPreferencesViewModel(settingsManager: settings)
        {
            IsAutoUpdateEnabled = false,
            SelectedThemeModeIndex = 1 // 淺色
        };

        vm.ResetAllSettingsCommand.Execute(null);

        Assert.True(vm.IsAutoUpdateEnabled);
        Assert.Equal(0, vm.SelectedThemeModeIndex);
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

    private sealed class MockUpdateChecker(Core.Ports.UpdateCheckResult result) : Core.Ports.IUpdateCheckerService
    {
        public Task<Core.Ports.UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(result);
    }
}
