using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageServerChildViewModelTests : IDisposable
{
    private readonly TempDirectory _rootTemp = new("msm-manage-child-");
    private readonly string _root;
    private readonly FakeServerRuntimeHost _host = new();
    private readonly MonitorUiService _ui = new();
    private ServerStopCoordinator? _coordinator;

    private sealed class FakeMonitorWindow : IMonitorWindow
    {
        public bool IsOpen { get; set; } = true;
        public int BringToFrontCount { get; private set; }
        public int CloseCount { get; private set; }
        public ServerMonitorViewModel? ViewModel { get; init; }

        public event Action? Closed;

        public void BringToFront() => BringToFrontCount++;

        public void Close()
        {
            CloseCount++;
            IsOpen = false;
            Closed?.Invoke();
        }
    }

    private sealed class MonitorUiService : ManualUiService
    {
        public List<FakeMonitorWindow> Windows { get; } = [];
        public Queue<string?> FolderPickQueue { get; } = new();
        public Func<RestoreBackupViewModel, Task<bool?>>? OnShowRestoreBackup { get; set; }

        public override Task<string?> PickFolderAsync(string title, string? initialDirectory = null) =>
            FolderPickQueue.Count > 0
                ? Task.FromResult(FolderPickQueue.Dequeue())
                : base.PickFolderAsync(title, initialDirectory);

        public override Task<bool?> ShowRestoreBackupAsync(RestoreBackupViewModel viewModel) =>
            OnShowRestoreBackup is not null
                ? OnShowRestoreBackup(viewModel)
                : base.ShowRestoreBackupAsync(viewModel);

        public override IMonitorWindow OpenServerMonitor(ServerMonitorViewModel viewModel)
        {
            var window = new FakeMonitorWindow { ViewModel = viewModel };
            Windows.Add(window);
            return window;
        }
    }

    private IEnumerable<(string Message, NotificationType Type)> Notifications =>
        _ui.Notifications.Select(static n => (n.Message, n.Type));

    public ManageServerChildViewModelTests()
    {
        _root = _rootTemp.FullName;
    }

    public void Dispose() => _rootTemp.Dispose();

    private (ManageServerViewModel Vm, ServerManager Manager) CreateViewModel()
    {
        var settings = TestDependencies.CreateSettings(_root);
        var deps = TestDependencies.Create(_root, _ui, settings: settings, runtimeHost: _host);
        _coordinator = deps.StopCoordinator;
        return (TestDependencies.CreateManagePage(deps), (ServerManager)deps.ServerManager);
    }

    [Theory]
    [InlineData(ServerBackupSummaryStatus.NotConfigured, "未設定外部備份")]
    [InlineData(ServerBackupSummaryStatus.DirectoryMissing, "備份資料夾不存在")]
    [InlineData(ServerBackupSummaryStatus.NoBackups, "尚無備份")]
    [InlineData(ServerBackupSummaryStatus.ReadFailed, "讀取備份失敗")]
    public void FormatBackupStatus_SummaryState_MapsText(ServerBackupSummaryStatus status, string expected) => Assert.Equal(expected, ServerStatusFormatter.FormatBackupStatus(new ServerBackupSummary(status)));

    [Fact]
    public void FormatBackupStatus_HasBackups_IncludesCountAndRelativeTime()
    {
        string text = ServerStatusFormatter.FormatBackupStatus(new ServerBackupSummary(ServerBackupSummaryStatus.HasBackups, 3, DateTime.Now));

        Assert.Equal("3 個備份（剛剛）", text);
    }

    [Theory]
    [InlineData(0, "剛剛")]
    [InlineData(5, "5 分鐘前")]
    [InlineData(180, "3 小時前")]
    [InlineData(60 * 50, "2 天前")]
    [InlineData(-10, "剛剛")]
    public void FormatRelativeTime_Elapsed_UsesLargestUnit(int minutesAgo, string expected) => Assert.Equal(expected, ServerStatusFormatter.FormatRelativeTime(DateTime.Now.AddMinutes(-minutesAgo)));

    [Fact]
    public void SelectedServer_Changed_RefreshesChildCommands()
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
    public void CanManagePlayers_SelectedServerRunning_IsFalse()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            _host.GetFake("Live").IsRunning = true;

            vm.List.SelectedServer = new ServerRowItem { Name = "Live", Status = "已停止" };

            Assert.True(vm.List.IsSelectedServerActive);
            Assert.False(vm.List.CanManagePlayers);
        }
    }

    [Fact]
    public async Task StartServerByName_WhenSameServerRunning_NotifiesAndDoesNotStart()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            _host.GetFake("Any").IsRunning = true;

            bool started = await vm.Lifecycle.StartServerByNameAsync("any");

            Assert.False(started);
            Assert.Equal(0, _host.GetFake("Any").StartCount);
            Assert.Contains(Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("已在執行中", StringComparison.Ordinal));
        }
    }

    [Fact]
    public async Task StopServer_SelectedRunningServer_StopsGracefullyViaCoordinator()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            var runtime = _host.GetFake("Live");
            runtime.IsRunning = true;
            runtime.WaitResults.Enqueue(new ProcessExitResult(0, false));
            vm.List.SelectedServer = new ServerRowItem { Name = "Live", Path = _root };

            await vm.Lifecycle.StopServerCommand.ExecuteAsync(null);

            Assert.Equal(["stop"], runtime.SentCommands);
            Assert.Equal(0, runtime.StopCount);
            Assert.False(runtime.IsRunning);
            Assert.DoesNotContain(Notifications, static n => n.Type == NotificationType.Error);
        }
    }

    [Fact]
    public async Task StopServer_SelectedServerNotRunning_DoesNothing()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            var runtime = _host.GetFake("Idle");
            vm.List.SelectedServer = new ServerRowItem { Name = "Idle", Path = _root };

            await vm.Lifecycle.StopServerCommand.ExecuteAsync(null);

            Assert.Empty(runtime.SentCommands);
            Assert.Equal(0, runtime.StopCount);
        }
    }

    [Fact]
    public void MonitorServerByName_DifferentServers_OpenSeparateWindows()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            vm.Lifecycle.MonitorServerByName("A", _root, "1.21.4");
            vm.Lifecycle.MonitorServerByName("B", _root, "1.21.4");
            vm.Lifecycle.MonitorServerByName("A", _root, "1.21.4");

            Assert.Equal(2, _ui.Windows.Count);
            Assert.Equal(1, _ui.Windows[0].BringToFrontCount);
            Assert.Equal(0, _ui.Windows[1].BringToFrontCount);
        }
    }

    [Fact]
    public void MonitorServerByName_TwoServers_ReceivesOnlyOwnOutput()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            vm.Lifecycle.MonitorServerByName("A", _root, "1.21.4");
            vm.Lifecycle.MonitorServerByName("B", _root, "1.21.4");

            _host.GetFake("A").RaiseOutputLine("[12:00:00] [Server thread/INFO]: only-for-a");
            _host.GetFake("B").RaiseOutputLine("[12:00:00] [Server thread/INFO]: only-for-b");

            _ui.TickRunningTimers();
            var monitorA = _ui.Windows[0].ViewModel!;
            var monitorB = _ui.Windows[1].ViewModel!;
            Assert.Contains(monitorA.Logs, static l => l.Contains("only-for-a", StringComparison.Ordinal));
            Assert.DoesNotContain(monitorA.Logs, static l => l.Contains("only-for-b", StringComparison.Ordinal));
            Assert.Contains(monitorB.Logs, static l => l.Contains("only-for-b", StringComparison.Ordinal));
            Assert.DoesNotContain(monitorB.Logs, static l => l.Contains("only-for-a", StringComparison.Ordinal));
        }
    }

    [Fact]
    public void Dispose_OpenMonitors_ClosesAll()
    {
        var (vm, _) = CreateViewModel();
        vm.Lifecycle.MonitorServerByName("A", _root, "1.21.4");
        vm.Lifecycle.MonitorServerByName("B", _root, "1.21.4");

        vm.Dispose();

        Assert.All(_ui.Windows, static w => Assert.Equal(1, w.CloseCount));
    }

    [Fact]
    public async Task DeleteServer_WhenRunning_NotifiesAndDoesNotDelete()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("Busy"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
            Assert.True(created.Completed);
            await vm.List.RefreshAndSelectServerAsync("Busy");
            _host.GetFake("Busy").IsRunning = true;

            await vm.DeleteServerCommand.ExecuteAsync(null);

            Assert.True(Directory.Exists(created.Config!.Path));
            Assert.Contains(Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("正在執行中", StringComparison.Ordinal));
        }
    }

    [Fact]
    public async Task UpdateServerStatusInPlaceAsync_Stopping_ShowsStoppingUntilFinished()
    {
        var (vm, _) = CreateViewModel();
        using (vm)
        {
            var runtime = _host.GetFake("Live");
            runtime.IsRunning = true;
            runtime.WaitResults.Enqueue(null);
            _ui.ChoiceGate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            vm.List.Servers.Add(new ServerRowItem { Name = "Live", Path = _root, Status = "執行中" });

            var stopTask = _coordinator!.StopAsync("Live");
            await vm.List.UpdateServerStatusInPlaceAsync();
            Assert.Equal("停止中", vm.List.Servers.Single(static s => s.Name == "Live").Status);

            _ui.ChoiceGate.SetResult(true);
            await stopTask;
            await vm.List.UpdateServerStatusInPlaceAsync();
            Assert.NotEqual("停止中", vm.List.Servers.Single(static s => s.Name == "Live").Status);
        }
    }

    [Fact]
    public async Task StartServerByName_WhenAnotherServerRunning_StillStarts()
    {
        var settings = TestDependencies.CreateSettings(_root);
        var deps = TestDependencies.Create(_root, _ui, settings: settings, runtimeHost: _host, javaDetector: new FixedJavaRuntimeDetector(21, "java.exe"), javaRequirementService: new FixedJavaRequirementService(21));
        using var vm = TestDependencies.CreateManagePage(deps);
        var manager = (ServerManager)deps.ServerManager;
        var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
            name: ServerName.Parse("Target"),
            minecraftVersion: MinecraftVersion.Parse("1.21.4"),
            loaderType: LoaderKind.Vanilla,
            memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(created.Completed);

        // 另一台伺服器執行中，且使用不同連接埠
        Directory.CreateDirectory(Path.Combine(_root, "Other"));
        File.WriteAllText(Path.Combine(_root, "Other", "server.properties"), "server-port=25566\n");
        _host.GetFake("Other").IsRunning = true;

        bool started = await vm.Lifecycle.StartServerByNameAsync("Target");

        Assert.True(started);
        Assert.Equal(1, _host.GetFake("Target").StartCount);
        Assert.True(_host.GetFake("Other").IsRunning);
    }

    [Fact]
    public async Task StartServerByName_WhenJavaMajorDiffersFromOfficial_BlocksAndShowsError()
    {
        var settings = TestDependencies.CreateSettings(_root);
        var deps = TestDependencies.Create(_root, _ui, settings: settings, runtimeHost: _host, javaDetector: new FixedJavaRuntimeDetector(21), javaRequirementService: new FixedJavaRequirementService(17));
        using var vm = TestDependencies.CreateManagePage(deps);
        var manager = (ServerManager)deps.ServerManager;
        var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
            name: ServerName.Parse("Mismatch"),
            minecraftVersion: MinecraftVersion.Parse("1.20.1"),
            loaderType: LoaderKind.Vanilla,
            memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);

        bool started = await vm.Lifecycle.StartServerByNameAsync("Mismatch");

        Assert.True(created.Completed);
        Assert.False(started);
        Assert.Single(_ui.ErrorMessages);
        Assert.Equal(0, _host.GetFake("Mismatch").StartCount);
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
                memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
            Assert.True(created.Completed);
            foreach (string jar in Directory.EnumerateFiles(created.Config!.Path, "*.jar"))
            {
                File.Delete(jar);
            }

            bool started = await vm.Lifecycle.StartServerByNameAsync("NoJar");

            Assert.False(started);
            Assert.Equal(0, _host.GetFake("NoJar").StartCount);
            Assert.Single(_ui.ErrorMessages);
            Assert.DoesNotContain(Notifications, static n => n.Type == NotificationType.Error);
        }
    }

    [Fact]
    public async Task BackupServer_ValidServer_CreatesBackupAndRefreshesStatus()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("Backed"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
            Assert.True(created.Completed);
            using var externalDirTemp = new TempDirectory("msm-manage-child-ext-");
            string externalDir = Path.Combine(externalDirTemp.FullName, "root");
            var config = created.Config!;
            await manager.UpdateServerAsync(
                new ServerConfig(config.Name, config.MinecraftVersion, config.LoaderType, config.LoaderVersion, config.MemoryMaxMb, config.MemoryMinMb, config.Path, config.JvmArgs, externalDir),
                TestContext.Current.CancellationToken);
            await vm.List.RefreshAndSelectServerAsync("Backed");

            await vm.Backup.BackupServerCommand.ExecuteAsync(null);

            Assert.Single(Directory.EnumerateFiles(externalDir, "backup-Backed-*.zip"));
            Assert.StartsWith("1 個備份", vm.List.SelectedServer!.BackupStatus, StringComparison.Ordinal);
        }
    }

    [Fact]
    public async Task BackupServer_WhenRunning_NotifiesAndDoesNotCreateBackup()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("RunningBackup"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
            Assert.True(created.Completed);
            using var externalDirTemp = new TempDirectory("msm-manage-child-ext-");
            var config = created.Config!;
            await manager.UpdateServerAsync(
                new ServerConfig(config.Name, config.MinecraftVersion, config.LoaderType, config.LoaderVersion, config.MemoryMaxMb, config.MemoryMinMb, config.Path, config.JvmArgs, externalDirTemp.FullName),
                TestContext.Current.CancellationToken);
            await vm.List.RefreshAndSelectServerAsync("RunningBackup");
            _host.GetFake("RunningBackup").IsRunning = true;

            await vm.Backup.BackupServerCommand.ExecuteAsync(null);

            Assert.Empty(Directory.EnumerateFiles(externalDirTemp.FullName, "*.zip"));
            Assert.Contains(Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("正在執行中", StringComparison.Ordinal));
        }
    }

    [Fact]
    public void Dispose_AfterUse_UnsubscribesRuntimeAndChildHandlers()
    {
        var (vm, _) = CreateViewModel();
        Assert.True(_host.SubscriberCount > 0);

        vm.Dispose();

        Assert.Equal(0, _host.SubscriberCount);
    }

    [Fact]
    public async Task EditBackupPathCommand_SubdirectoryThenValidFolder_RejectsSubdirectoryAndUpdatesValid()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("PathCheck"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
            Assert.True(created.Completed);
            await vm.List.RefreshAndSelectServerAsync("PathCheck");

            using var externalDirTemp = new TempDirectory("msm-manage-child-valid-");
            string serverSubdir = Path.Combine(created.Config!.Path, "backups");
            _ui.FolderPickQueue.Enqueue(serverSubdir);
            _ui.FolderPickQueue.Enqueue(externalDirTemp.FullName);

            await vm.Backup.EditBackupPathCommand.ExecuteAsync(null);

            Assert.Contains(Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("不得位於", StringComparison.Ordinal));
            Assert.Contains(Notifications, static n => n.Type == NotificationType.Success && n.Message.Contains("備份資料夾路徑", StringComparison.Ordinal));
            Assert.Equal(externalDirTemp.FullName, vm.List.SelectedServer!.BackupPath);
        }
    }

    [Fact]
    public async Task RestoreBackupCommand_Confirmed_RestoresFilesAndRefreshesServer()
    {
        var (vm, manager) = CreateViewModel();
        using (vm)
        {
            var created = await manager.CreateServerAsync(ServerCreationPlan.Create(
                name: ServerName.Parse("Restorable"),
                minecraftVersion: MinecraftVersion.Parse("1.21.4"),
                loaderType: LoaderKind.Vanilla,
                memoryMaxMb: 1024), cancellationToken: TestContext.Current.CancellationToken);
            Assert.True(created.Completed);

            using var externalDirTemp = new TempDirectory("msm-manage-child-restore-");
            var config = created.Config!;
            string markerFile = Path.Combine(config.Path, "world-marker.txt");
            await File.WriteAllTextAsync(markerFile, "original-state", TestContext.Current.CancellationToken);
            await manager.UpdateServerAsync(
                new ServerConfig(config.Name, config.MinecraftVersion, config.LoaderType, config.LoaderVersion, config.MemoryMaxMb, config.MemoryMinMb, config.Path, config.JvmArgs, externalDirTemp.FullName),
                TestContext.Current.CancellationToken);
            await vm.List.RefreshAndSelectServerAsync("Restorable");

            // 建立真實備份，再竄改檔案以驗證還原效果
            await vm.Backup.BackupServerCommand.ExecuteAsync(null);
            await File.WriteAllTextAsync(markerFile, "modified-state", TestContext.Current.CancellationToken);

            _ui.OnShowRestoreBackup = async restoreVm =>
            {
                await TestWait.UntilAsync(() => restoreVm.Backups.Count > 0, "備份清單載入");
                await restoreVm.RestoreCommand.ExecuteAsync(null);
                return true;
            };

            await vm.Backup.RestoreBackupCommand.ExecuteAsync(null);

            Assert.Equal("original-state", await File.ReadAllTextAsync(markerFile, TestContext.Current.CancellationToken));
            Assert.Equal("Restorable", vm.List.SelectedServer?.Name);
            Assert.DoesNotContain(Notifications, static n => n.Type == NotificationType.Error);
        }
    }
}
