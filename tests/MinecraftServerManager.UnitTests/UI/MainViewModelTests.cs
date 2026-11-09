using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed partial class MainViewModelTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MainViewModelTests));
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
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    private MainViewModel CreateIsolatedViewModel(string themeMode = "dark", IUiService? uiService = null)
    {
        var settings = new Infrastructure.Settings.SettingsManager(_testDir);
        settings.SetThemeMode(themeMode);
        var deps = TestDependencies.Create(_testDir, uiService, settings: settings);
        return new MainViewModel(deps);
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
        var ui = new RecordingUiService();
        var vm = CreateIsolatedViewModel(uiService: ui);
        var initialPage = vm.CurrentPage;

        vm.Navigate("nonexistent_page");

        Assert.Same(initialPage, vm.CurrentPage);
        Assert.Equal(NotificationType.Error, ui.LastType);
        Assert.Contains("找不到頁面", ui.LastMessage);
    }

    [Fact]
    public void ActionCommandsShouldTriggerNotifications()
    {
        var ui = new ConfirmingImportUiService();
        var vm = CreateIsolatedViewModel(uiService: ui);

        vm.ImportServerCommand.Execute(null);
        Assert.Contains("匯入", ui.LastMessage);
    }

    private class RecordingUiService : NoOpUiService
    {
        public string? LastMessage { get; private set; }

        public NotificationType? LastType { get; private set; }

        public override void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info)
        {
            LastMessage = message;
            LastType = type;
        }
    }

    private sealed class ConfirmingImportUiService : RecordingUiService
    {
        public override Task<bool?> ShowImportServerAsync(ImportServerViewModel viewModel) => Task.FromResult<bool?>(true);
    }
}
