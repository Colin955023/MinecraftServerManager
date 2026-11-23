using System.Text;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerMonitorViewModelTests : IDisposable
{
    private readonly TempDirectory _tempRootTemp = new("msm-monitor-test-");
    private readonly string _tempRoot;
    private readonly string _tempServerDir;
    private readonly FakeServerRuntime _runtime;
    private readonly ServerLogReader _logReader = new();
    private readonly ServerPropertiesStore _propertiesStore;

    public ServerMonitorViewModelTests()
    {
        _tempRoot = _tempRootTemp.FullName;
        _tempServerDir = Path.Combine(_tempRoot, "TestServer");
        Directory.CreateDirectory(_tempServerDir);
        _propertiesStore = new ServerPropertiesStore(_tempRoot);
        _runtime = new FakeServerRuntime();
        var host = new FakeServerRuntimeHost();
        host.Add("TestServer", _runtime);
        StopCoordinator = new ServerStopCoordinator(NoOpUiService.Instance, host);
    }

    private ServerStopCoordinator StopCoordinator { get; }

    public void Dispose() => _tempRootTemp.Dispose();

    [Theory]
    [InlineData("[12:00:00] [Server thread/INFO]: Steve joined the game", "Steve")]
    [InlineData("[12:00:00] [Server thread/INFO] [minecraft/MinecraftServer]: Steve joined the game", "Steve")]
    [InlineData("[12:00:00] [Server thread/INFO]: .Steve joined the game", ".Steve")]
    public void PlayerJoin_RealLogFormats_AreRecognized(string line, string expectedPlayer)
    {
        using var vm = CreateMonitor();

        _runtime.RaiseOutputLine(line);

        Assert.Equal([expectedPlayer], vm.OnlinePlayers.ToArray());
    }

    [Theory]
    [InlineData("[12:00:00] [Server thread/INFO]: <Alice> hi: Bob joined the game")]
    [InlineData("[12:00:00] [Server thread/INFO]: <Alice> ]: Bob joined the game")]
    [InlineData("[12:00:00] [Server thread/INFO]: <Alice> ]: Bob left the game")]
    public void OutputLine_SpoofedJoinChat_KeepsOnlinePlayers(string line)
    {
        using var vm = CreateMonitor();

        _runtime.RaiseOutputLine(line);

        Assert.Empty(vm.OnlinePlayers);
    }

    [Fact]
    public void OutputLine_SpoofedPlayerCount_KeepsCount()
    {
        using var vm = CreateMonitor();
        _runtime.RaiseOutputLine("[12:00:00] [Server thread/INFO]: There are 1 of a max of 20 players online: Steve");
        Assert.Equal("1 / 20", vm.OnlinePlayersText);

        _runtime.RaiseOutputLine("[12:00:01] [Server thread/INFO]: <Alice> There are 9 of a max of 20 players online: Bob");

        Assert.Equal("1 / 20", vm.OnlinePlayersText);
        Assert.Equal(["Steve"], vm.OnlinePlayers.ToArray());
    }

    [Theory]
    [InlineData(0, 0, 5, "00:00:05")]
    [InlineData(25, 3, 9, "25:03:09")]
    [InlineData(100, 59, 59, "100:59:59")]
    public void FormatUptime_Over24Hours_DoesNotWrap(int hours, int minutes, int seconds, string expected) =>
        Assert.Equal(expected, ServerMonitorViewModel.FormatUptime(new TimeSpan(hours, minutes, seconds)));

    [Fact]
    public void PlayerJoinLeave_CaseInsensitive_UpdatesCountWithMaxPlayers()
    {
        using var vm = CreateMonitor();
        _runtime.RaiseOutputLine("[12:00:00] [Server thread/INFO]: There are 0 of a max of 50 players online:");

        _runtime.RaiseOutputLine("[12:00:01] [Server thread/INFO]: Steve joined the game");
        _runtime.RaiseOutputLine("[12:00:02] [Server thread/INFO]: steve joined the game");
        Assert.Equal("1 / 50", vm.OnlinePlayersText);

        _runtime.RaiseOutputLine("[12:00:03] [Server thread/INFO]: STEVE left the game");
        Assert.Empty(vm.OnlinePlayers);
        Assert.Equal("0 / 50", vm.OnlinePlayersText);
    }

    [Fact]
    public void Commands_ServerStopped_AreDisabled()
    {
        _runtime.IsRunning = false;
        using var vm = CreateMonitor();

        Assert.False(vm.SendCommandCommand.CanExecute(null));
        Assert.False(vm.ForceKillCommand.CanExecute(null));
    }

    [Fact]
    public void OutputLine_AfterDispose_IsIgnored()
    {
        var vm = CreateMonitor();
        vm.Dispose();

        _runtime.RaiseOutputLine("[12:00:00] [Server thread/INFO]: Steve joined the game");

        Assert.Empty(vm.OnlinePlayers);
    }

    private ServerMonitorViewModel CreateMonitor() =>
        new(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);

    [Fact]
    public async Task StopServerCommand_Running_StopsGracefullyViaCoordinator()
    {
        _runtime.IsRunning = true;
        _runtime.WaitResults.Enqueue(new ProcessExitResult(0, false));
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);

        await vm.StopServerCommand.ExecuteAsync(null);

        Assert.Equal(["stop"], _runtime.SentCommands);
        Assert.Equal(0, _runtime.StopCount);
    }

    [Fact]
    public void NavigateHistory_WithoutSentCommands_ReturnsNullAndKeepsText()
    {
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);
        vm.CommandText = "draft";

        Assert.Null(vm.NavigateHistory(previous: true));
        Assert.Null(vm.NavigateHistory(previous: false));
        Assert.Equal("draft", vm.CommandText);
    }

    [Fact]
    public async Task NavigateHistory_SentCommands_BrowsesAndRestoresDraft()
    {
        _runtime.IsRunning = true;
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);

        foreach (string command in (string[])["list", "say hi", "say hi", "  op Steve  "])
        {
            vm.CommandText = command;
            await vm.SendCommandAsync();
        }

        Assert.Equal(string.Empty, vm.CommandText);
        vm.CommandText = "draft";

        // 往上：由最新往最舊，連續重複的指令只記一次，到頂後停在最舊一筆
        Assert.Equal("op Steve", vm.NavigateHistory(previous: true));
        Assert.Equal("say hi", vm.NavigateHistory(previous: true));
        Assert.Equal("list", vm.NavigateHistory(previous: true));
        Assert.Equal("list", vm.NavigateHistory(previous: true));

        // 往下：回到最新後再往下還原草稿，之後維持草稿
        Assert.Equal("say hi", vm.NavigateHistory(previous: false));
        Assert.Equal("op Steve", vm.NavigateHistory(previous: false));
        Assert.Equal("draft", vm.NavigateHistory(previous: false));
        Assert.Equal("draft", vm.NavigateHistory(previous: false));

        // 送出新指令後從最新一筆重新開始
        vm.CommandText = "stop";
        await vm.SendCommandAsync();
        Assert.Equal("stop", vm.NavigateHistory(previous: true));
    }

    [Fact]
    public void ParsesPlayerList_DifferentCoreFormats_UpdatesCountAndPlayerList()
    {
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);

        // 格式 1: Vanilla / Paper 繁複格式: There are 2 of a max of 20 players online: Steve, Alex
        _runtime.RaiseOutputLine("[12:00:00 INFO]: There are 2 of a max of 20 players online: Steve, Alex");

        Assert.Equal("2 / 20", vm.OnlinePlayersText);
        Assert.Equal(2, vm.OnlinePlayers.Count);
        Assert.Contains("Steve", vm.OnlinePlayers);
        Assert.Contains("Alex", vm.OnlinePlayers);
        Assert.False(vm.HasNoOnlinePlayers);

        // 格式 2: 簡短斜線格式: There are 1/20 players online: Steve
        _runtime.RaiseOutputLine("[12:01:00 INFO]: There are 1/20 players online: Steve");

        Assert.Equal("1 / 20", vm.OnlinePlayersText);
        Assert.Single(vm.OnlinePlayers);
        Assert.Contains("Steve", vm.OnlinePlayers);

        // 格式 3: 0 人線上: There are 0 of a max 20 players online:
        _runtime.RaiseOutputLine("[12:02:00 INFO]: There are 0 of a max 20 players online:");

        Assert.Equal("0 / 20", vm.OnlinePlayersText);
        Assert.Empty(vm.OnlinePlayers);
        Assert.True(vm.HasNoOnlinePlayers);
    }

    [Fact]
    public void OutputLine_PlayerJoinAndLeave_UpdatesOnlinePlayers()
    {
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);

        _runtime.RaiseOutputLine("[12:00:00 INFO]: PlayerOne joined the game");
        Assert.Single(vm.OnlinePlayers);
        Assert.Contains("PlayerOne", vm.OnlinePlayers);

        _runtime.RaiseOutputLine("[12:01:00 INFO]: PlayerTwo joined the game");
        Assert.Equal(2, vm.OnlinePlayers.Count);
        Assert.Contains("PlayerTwo", vm.OnlinePlayers);

        _runtime.RaiseOutputLine("[12:02:00 INFO]: PlayerOne left the game");
        Assert.Single(vm.OnlinePlayers);
        Assert.DoesNotContain("PlayerOne", vm.OnlinePlayers);
        Assert.Contains("PlayerTwo", vm.OnlinePlayers);
    }

    [Fact]
    public async Task Constructor_ExistingLog_LoadsHistory()
    {
        string logsDir = Path.Combine(_tempServerDir, "logs");
        Directory.CreateDirectory(logsDir);
        string logFile = Path.Combine(logsDir, "latest.log");

        var utf8NoBom = new UTF8Encoding(false);
        File.WriteAllLines(logFile, ["Line 1", "Line 2", "Line 3", "Line 4", "Line 5"], utf8NoBom);

        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, StopCoordinator, static () => Task.CompletedTask);

        // 歷史紀錄於背景載入
        await TestWait.UntilAsync(() => vm.Logs.Count >= 5, "歷史日誌載入");

        Assert.Equal(5, vm.Logs.Count);
        Assert.Equal("Line 1", vm.Logs[0]);
        Assert.Equal("Line 5", vm.Logs[4]);
    }

    [Fact]
    public async Task ServerReady_ReadsPropertiesUnderConcurrentAccess_ShowsNotification()
    {
        string propsPath = Path.Combine(_tempServerDir, "server.properties");
        File.WriteAllText(propsPath, "server-port=25577\nserver-ip=127.0.0.1\n");

        // 模擬外部行程（例如 Minecraft Java 伺服器）正以可讀可寫並行模式開啟該檔案
        using var lockingStream = new FileStream(propsPath, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite);

        var mockUi = new ManualUiService();
        _runtime.IsRunning = true;
        _runtime.IsReady = false;
        using var vm = new ServerMonitorViewModel(
            _runtime,
            _logReader,
            _propertiesStore,
            "TestServer",
            mockUi,
            _tempServerDir,
            string.Empty,
            StopCoordinator,
            static () => Task.CompletedTask);

        _runtime.RaiseReady();

        await TestWait.UntilAsync(() => mockUi.LastNotification is not null, "就緒通知");

        Assert.NotNull(mockUi.LastNotification);
        Assert.Contains("25577", mockUi.LastNotification.Value.Message);
        Assert.Contains("127.0.0.1", mockUi.LastNotification.Value.Message);
    }

    [Fact]
    public void OutputLine_Burst_TrimsDisplayedLogsToLowWatermark()
    {
        var mockUi = new ManualUiService();
        _runtime.IsRunning = true;
        using var vm = new ServerMonitorViewModel(
            _runtime,
            _logReader,
            _propertiesStore,
            "TestServer",
            mockUi,
            _tempServerDir,
            string.Empty,
            StopCoordinator,
            static () => Task.CompletedTask);

        for (int i = 0; i < 6000; i++)
        {
            _runtime.RaiseOutputLine($"line-{i}");
        }

        mockUi.TickRunningTimers();

        Assert.Equal(1800, vm.Logs.Count);
        Assert.Equal("line-4200", vm.Logs[0]);
        Assert.Equal("line-5999", vm.Logs[^1]);
    }
}
