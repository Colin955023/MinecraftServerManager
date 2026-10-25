using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class MainViewModelTests : IDisposable
{
    private readonly string _testDir;

    public MainViewModelTests()
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
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
    }

    private MainViewModel CreateIsolatedViewModel(string themeMode = "dark", IUiService? uiService = null)
    {
        var settings = new Infrastructure.Settings.SettingsManager(_testDir);
        settings.SetThemeMode(themeMode);
        var dirSize = new Infrastructure.Servers.ServerDirectorySizeService();
        var inspector = new Infrastructure.Servers.ServerInspector(dirSize);
        var manager = new Infrastructure.Servers.ServerManager(_testDir, inspector);
        var backup = new Infrastructure.Servers.ServerBackupService(_testDir);
        var runner = new Infrastructure.Process.ProcessRunner();
        var runtime = new Infrastructure.Servers.ServerRuntime(runner);
        var launchPlanner = new Infrastructure.Servers.ServerLaunchPlanner();
        var propsStore = new Infrastructure.Servers.ServerPropertiesStore(_testDir);
        var playerConfig = new Infrastructure.Servers.ServerPlayerConfigStore();
        var integrity = new Infrastructure.Servers.ServerIntegrityService();
        var depPlanner = new Infrastructure.Mods.ModDependencyPlanner();
        var exporter = new Infrastructure.Mods.ModListExporter();

        var deps = new MainViewModelDependencies(
            SettingsManager: settings,
            ServerManager: manager,
            BackupService: backup,
            ServerRuntime: runtime,
            ServerInspector: inspector,
            LaunchPlanner: launchPlanner,
            PropertiesStore: propsStore,
            PlayerConfigStore: playerConfig,
            DirectorySizeService: dirSize,
            IntegrityService: integrity,
            DependencyPlanner: depPlanner,
            ModListExporter: exporter,
            UiService: uiService);

        return new MainViewModel(deps);
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
        var vm = CreateIsolatedViewModel(uiService: new ConfirmingImportUiService());

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

    [Fact]
    public void ToggleThemeShouldInvertThemeStateFromLight()
    {
        var vm = CreateIsolatedViewModel(themeMode: "light");
        Assert.True(vm.IsLightTheme);

        vm.ToggleThemeCommand.Execute(null);
        Assert.False(vm.IsLightTheme);
        Assert.True(vm.IsNotificationVisible);

        vm.ToggleThemeCommand.Execute(null);
        Assert.True(vm.IsLightTheme);
    }

    private sealed class ConfirmingImportUiService : NoOpUiService
    {
        public override bool? ShowImportServer(ImportServerViewModel viewModel) => true;
    }
}
