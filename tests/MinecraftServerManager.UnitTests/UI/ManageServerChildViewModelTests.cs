using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 伺服器管理頁子 ViewModel 測試（清單格式化、選取連動命令、生命週期、備份與釋放）
/// </summary>
public sealed class ManageServerChildViewModelTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ManageServerChildViewModelTests));
    private readonly string _root;
    private readonly FakeServerRuntime _runtime = new();
    private readonly ManualUiService _ui = new();

    private IEnumerable<(string Message, NotificationType Type)> Notifications =>
        _ui.Notifications.Select(static n => (n.Message, n.Type));

    public ManageServerChildViewModelTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "msm-manage-child-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_root))
            {
                Directory.Delete(_root, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    private (ManageServerViewModel Vm, ServerManager Manager) CreateViewModel()
    {
        var settings = new SettingsManager(_root);
        settings.SetExactServersRoot(_root);
        var deps = TestDependencies.Create(_root, _ui, settings: settings, runtime: _runtime);
        return (new ManageServerViewModel(deps, _ui, static _ => { }), (ServerManager)deps.ServerManager);
    }

    [Theory]
    [InlineData(ServerBackupSummaryStatus.NotConfigured, "未設定外部備份")]
    [InlineData(ServerBackupSummaryStatus.DirectoryMissing, "備份資料夾不存在")]
    [InlineData(ServerBackupSummaryStatus.NoBackups, "尚無備份")]
    [InlineData(ServerBackupSummaryStatus.ReadFailed, "讀取備份失敗")]
    public void FormatBackupStatus_MapsSummaryStates(ServerBackupSummaryStatus status, string expected) => Assert.Equal(expected, ServerListViewModel.FormatBackupStatus(new ServerBackupSummary(status)));

    [Fact]
    public void FormatBackupStatus_IncludesCountAndRelativeTime()
    {
        string text = ServerListViewModel.FormatBackupStatus(new ServerBackupSummary(ServerBackupSummaryStatus.HasBackups, 3, DateTime.Now));

        Assert.Equal("3 個備份（剛剛）", text);
    }

    [Theory]
    [InlineData(0, "剛剛")]
    [InlineData(5, "5 分鐘前")]
    [InlineData(180, "3 小時前")]
    [InlineData(60 * 50, "2 天前")]
    [InlineData(-10, "剛剛")]
    public void FormatRelativeTime_UsesLargestUnit(int minutesAgo, string expected) => Assert.Equal(expected, ServerListViewModel.FormatRelativeTime(DateTime.Now.AddMinutes(-minutesAgo)));

    [Fact]
    public void SelectionChange_RefreshesCommandsAcrossChildren()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            int canExecuteChanges = 0;
            vm.Lifecycle.StartServerCommand.CanExecuteChanged += (_, _) => canExecuteChanges++;
            vm.Backup.BackupServerCommand.CanExecuteChanged += (_, _) => canExecuteChanges++;
            vm.DeleteServerCommand.CanExecuteChanged += (_, _) => canExecuteChanges++;

            vm.List.SelectedServer = new ServerRowItem { Name = "A", Path = _root };

            Assert.Equal(3, canExecuteChanges);
            Assert.True(vm.Backup.EditBackupPathCommand.CanExecute(null));
            Assert.True(vm.RecheckServerCommand.CanExecute(null));
        }
    }

    [Fact]
    public void RunningSelectedServer_DisablesPlayerManagement()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            _runtime.IsRunning = true;
            _runtime.ActiveServerName = "Live";

            vm.List.SelectedServer = new ServerRowItem { Name = "Live", Status = "已停止" };

            Assert.True(vm.List.IsSelectedServerActive);
            Assert.False(vm.List.CanManagePlayers);
        }
    }

    [Fact]
    public async Task StartServerByName_WhenAnotherServerRunning_NotifiesAndDoesNotStart()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            _runtime.IsRunning = true;

            bool started = await vm.Lifecycle.StartServerByNameAsync("Any");

            Assert.False(started);
            Assert.Equal(0, _runtime.StartCount);
            Assert.Contains(Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("正在執行中", StringComparison.Ordinal));
        }
    }

    [Fact]
    public async Task StartServerByName_WithMissingLaunchTarget_ShowsSingleErrorDialog()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("NoJar"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024));
            Assert.True(created.Completed);
            foreach (string jar in Directory.EnumerateFiles(created.Config!.Path, "*.jar"))
            {
                File.Delete(jar);
            }

            bool started = await vm.Lifecycle.StartServerByNameAsync("NoJar");

            Assert.False(started);
            Assert.Equal(0, _runtime.StartCount);
            Assert.Single(_ui.ErrorMessages);
            Assert.DoesNotContain(Notifications, static n => n.Type == NotificationType.Error);
        }
    }

    [Fact]
    public async Task BackupServer_CreatesBackupAndRefreshesBackupStatus()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("Backed"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024));
            Assert.True(created.Completed);
            string externalDir = Path.Combine(Path.GetTempPath(), "msm-manage-child-ext-" + Guid.NewGuid().ToString("N"));
            try
            {
                var config = created.Config!;
                await manager.UpdateServerAsync(new ServerConfig(config.Name, config.MinecraftVersion, config.LoaderType, config.LoaderVersion, config.MemoryMaxMb, config.MemoryMinMb, config.Path, config.JvmArgs, externalDir));
                await vm.List.RefreshAndSelectServerAsync("Backed");

                await vm.Backup.BackupServerCommand.ExecuteAsync(null);

                Assert.Single(Directory.EnumerateFiles(externalDir, "backup-Backed-*.zip"));
                Assert.StartsWith("1 個備份", vm.List.SelectedServer!.BackupStatus, StringComparison.Ordinal);
            }
            finally
            {
                if (Directory.Exists(externalDir))
                {
                    Directory.Delete(externalDir, recursive: true);
                }
            }
        }
    }

    [Fact]
    public void Dispose_UnsubscribesRuntimeEventsAndChildHandlers()
    {
        var (vm, _) = CreateViewModel();
        Assert.True(_runtime.SubscriberCount > 0);

        vm.Dispose();

        Assert.Equal(0, _runtime.SubscriberCount);
    }
}
