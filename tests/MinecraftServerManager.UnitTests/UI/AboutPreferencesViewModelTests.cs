using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class AboutPreferencesViewModelTests
{
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
        string dir = Path.Combine(Path.GetTempPath(), "msm_test_" + Guid.NewGuid().ToString("N"));
        var settings = new Infrastructure.Settings.SettingsManager(dir);
        var vm = new AboutPreferencesViewModel(settingsManager: settings)
        {
            IsRememberSizePositionEnabled = false,
            IsAutoCenterEnabled = false,
            IsAutoUpdateEnabled = false,
            SelectedThemeModeIndex = 1 // 淺色
        };

        vm.ResetAllSettingsCommand.Execute(null);

        Assert.True(vm.IsRememberSizePositionEnabled);
        Assert.True(vm.IsAutoCenterEnabled);
        Assert.True(vm.IsAutoUpdateEnabled);
        Assert.Equal(0, vm.SelectedThemeModeIndex);
    }
}
