using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class MainViewModelTests
{
    private static MainViewModel CreateIsolatedViewModel()
    {
        string dir = Path.Combine(Path.GetTempPath(), "msm_test_" + Guid.NewGuid().ToString("N"));
        var settings = new Infrastructure.Settings.SettingsManager(dir);
        return new MainViewModel(settingsManager: settings);
    }

    [Fact]
    public void InitialStateShouldShowCreateServerPage()
    {
        var vm = CreateIsolatedViewModel();

        // 預設呈現建立新伺服器頁面
        Assert.NotNull(vm.CurrentPage);
        Assert.Equal("create", vm.CurrentPage.Key);
        Assert.Equal("建立新伺服器", vm.PageTitle);
        Assert.False(string.IsNullOrWhiteSpace(vm.PageSubtitle));
        Assert.False(vm.IsNotificationVisible);
        Assert.False(vm.IsLightTheme);
    }

    [Theory]
    [InlineData("create", typeof(CreateServerViewModel), "建立新伺服器")]
    [InlineData("manage", typeof(ManageServerViewModel), "管理現有伺服器")]
    [InlineData("mods", typeof(ModsViewModel), "🧩 模組管理")]
    [InlineData("about_preferences", typeof(AboutPreferencesViewModel), "關於與設定")]
    public void NavigateShouldSwitchCurrentPageWhenKeyIsValid(string key, Type expectedType, string expectedTitle)
    {
        var vm = CreateIsolatedViewModel();

        vm.NavigateCommand.Execute(key);

        Assert.IsType(expectedType, vm.CurrentPage);
        Assert.Equal(key, vm.CurrentPage.Key);
        Assert.Equal(expectedTitle, vm.PageTitle);
    }

    [Fact]
    public void NavigateShouldShowErrorNotificationWhenKeyIsInvalid()
    {
        var vm = CreateIsolatedViewModel();
        var initialPage = vm.CurrentPage;

        vm.NavigateCommand.Execute("nonexistent_page");

        Assert.Same(initialPage, vm.CurrentPage);
        Assert.True(vm.IsNotificationVisible);
        Assert.True(vm.IsNotificationError);
        Assert.Contains("找不到頁面", vm.NotificationMessage);
    }

    [Fact]
    public void ActionCommandsShouldTriggerNotifications()
    {
        var vm = CreateIsolatedViewModel();

        vm.ImportServerCommand.Execute(null);
        Assert.True(vm.IsNotificationVisible);
        Assert.Contains("匯入", vm.NotificationMessage);

        vm.OpenServersFolderCommand.Execute(null);
        Assert.True(vm.IsNotificationVisible);
    }

    [Fact]
    public void DismissNotificationShouldHideNotificationBanner()
    {
        var vm = CreateIsolatedViewModel();
        vm.ShowNotification("測試通知", isError: false);
        Assert.True(vm.IsNotificationVisible);

        vm.DismissNotificationCommand.Execute(null);

        Assert.False(vm.IsNotificationVisible);
        Assert.Empty(vm.NotificationMessage);
    }

    [Fact]
    public void ToggleThemeShouldInvertThemeState()
    {
        var vm = CreateIsolatedViewModel();
        Assert.False(vm.IsLightTheme);

        vm.ToggleThemeCommand.Execute(null);
        Assert.True(vm.IsLightTheme);
        Assert.True(vm.IsNotificationVisible);

        vm.ToggleThemeCommand.Execute(null);
        Assert.False(vm.IsLightTheme);
    }
}
