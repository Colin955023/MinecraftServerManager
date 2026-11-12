using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed partial class MainViewModelTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm_test_");
    private readonly string _testDir;

    public MainViewModelTests()
    {
        _testDir = _testDirTemp.FullName;
    }

    public void Dispose() => _testDirTemp.Dispose();

    private MainViewModel CreateIsolatedViewModel(string themeMode = "dark", IUiService? uiService = null, Core.Ports.IRunningServerRegistry? registry = null)
    {
        var settings = new Infrastructure.Settings.SettingsManager(_testDir);
        settings.SetThemeMode(themeMode);
        var deps = TestDependencies.Create(_testDir, uiService, settings: settings, runningServerRegistry: registry);
        return TestDependencies.CreateMainViewModel(deps);
    }

    [Fact]
    public void InitialStateShouldShowCreateServerPage()
    {
        var vm = CreateIsolatedViewModel();

        // 預設呈現建立新伺服器頁面
        Assert.NotNull(vm.CurrentPage);
        Assert.IsType<CreateServerViewModel>(vm.CurrentPage);
        Assert.Equal("建立新伺服器", vm.CurrentPage.Title);
    }

    [Theory]
    [InlineData("create", typeof(CreateServerViewModel), "建立新伺服器")]
    [InlineData("manage", typeof(ManageServerViewModel), "管理現有伺服器")]
    [InlineData("mods", typeof(ModsViewModel), "🧩 模組管理")]
    [InlineData("about_preferences", typeof(AboutPreferencesViewModel), "關於與設定")]
    public void NavigateShouldSwitchCurrentPageWhenKeyIsValid(string key, Type expectedType, string expectedTitle)
    {
        var vm = CreateIsolatedViewModel();

        vm.Navigate(key);

        Assert.IsType(expectedType, vm.CurrentPage);
        Assert.Equal(expectedTitle, vm.CurrentPage.Title);
    }

    [Fact]
    public void NavigateShouldShowErrorNotificationWhenKeyIsInvalid()
    {
        var ui = new ManualUiService();
        var vm = CreateIsolatedViewModel(uiService: ui);
        var initialPage = vm.CurrentPage;

        vm.Navigate("nonexistent_page");

        Assert.Same(initialPage, vm.CurrentPage);
        Assert.Equal(NotificationType.Error, ui.LastNotification?.Type);
        Assert.Contains("找不到頁面", ui.LastNotification?.Message);
    }

    [Fact]
    public void ActionCommandsShouldTriggerNotifications()
    {
        var ui = new ManualUiService { ImportServerResult = true };
        var vm = CreateIsolatedViewModel(uiService: ui);

        vm.ImportServerCommand.Execute(null);
        Assert.Contains("匯入", ui.LastNotification?.Message);
    }

    private sealed class OrphanRegistry(params Core.Ports.TrackedServerProcess[] orphans) : Core.Ports.IRunningServerRegistry
    {
        public List<Core.Ports.TrackedServerProcess> Terminated { get; } = [];

        public void Record(string serverName, int pid) { }

        public void Remove(string serverName) { }

        public Task<IReadOnlyList<Core.Ports.TrackedServerProcess>> FindOrphansAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Ports.TrackedServerProcess>>(orphans);

        public Task<bool> TerminateAsync(Core.Ports.TrackedServerProcess process, CancellationToken cancellationToken = default)
        {
            Terminated.Add(process);
            return Task.FromResult(true);
        }
    }

    [Fact]
    public async Task CheckOrphanedServers_WhenNone_DoesNotAsk()
    {
        var ui = new ManualUiService();
        var vm = CreateIsolatedViewModel(uiService: ui, registry: new OrphanRegistry());

        await vm.CheckOrphanedServersOnStartupAsync();

        Assert.Empty(ui.ChoiceMessages);
    }

    [Fact]
    public async Task CheckOrphanedServers_WhenUserChoosesTerminate_TerminatesAll()
    {
        var ui = new ManualUiService();
        ui.ChoiceResults.Enqueue(true);
        var registry = new OrphanRegistry(new Core.Ports.TrackedServerProcess("A", 100, 1), new Core.Ports.TrackedServerProcess("B", 200, 2));
        var vm = CreateIsolatedViewModel(uiService: ui, registry: registry);

        await vm.CheckOrphanedServersOnStartupAsync();

        Assert.Equal(2, registry.Terminated.Count);
        Assert.Contains("PID 100", ui.ChoiceMessages[0].Message, StringComparison.Ordinal);
        Assert.Contains(ui.Notifications, static n => n.Type == NotificationType.Success);
    }

    [Fact]
    public async Task CheckOrphanedServers_WhenUserDefers_DoesNotTerminate()
    {
        var ui = new ManualUiService();
        ui.ChoiceResults.Enqueue(false);
        var registry = new OrphanRegistry(new Core.Ports.TrackedServerProcess("A", 100, 1));
        var vm = CreateIsolatedViewModel(uiService: ui, registry: registry);

        await vm.CheckOrphanedServersOnStartupAsync();

        Assert.Empty(registry.Terminated);
    }
}
