using System.Text;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 伺服器監控視窗 ViewModel 測試（驗證紀錄限制、重新整理清空重載與玩家名單解析）
/// </summary>
public sealed partial class ServerMonitorViewModelTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMonitorViewModelTests));
    private readonly string _tempRoot;
    private readonly string _tempServerDir;
    private readonly MockServerRuntime _runtime;
    private readonly ServerLogReader _logReader = new();
    private readonly ServerPropertiesStore _propertiesStore;

    public ServerMonitorViewModelTests()
    {
        _tempRoot = Path.Combine(Path.GetTempPath(), "msm-monitor-test-" + Guid.NewGuid().ToString("N"));
        _tempServerDir = Path.Combine(_tempRoot, "TestServer");
        Directory.CreateDirectory(_tempServerDir);
        _propertiesStore = new ServerPropertiesStore(_tempRoot);
        _runtime = new MockServerRuntime();
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempRoot))
            {
                Directory.Delete(_tempRoot, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    [Fact]
    public void ParsesPlayerList_DifferentCoreFormats_UpdatesCountAndPlayerList()
    {
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, static () => Task.CompletedTask);

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
    public void HandlesPlayerJoinAndLeave_UpdatesOnlinePlayersCorrectly()
    {
        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, static () => Task.CompletedTask);

        _runtime.RaiseOutputLine("[12:00:00 INFO]: : PlayerOne joined the game");
        Assert.Single(vm.OnlinePlayers);
        Assert.Contains("PlayerOne", vm.OnlinePlayers);

        _runtime.RaiseOutputLine("[12:01:00 INFO]: : PlayerTwo joined the game");
        Assert.Equal(2, vm.OnlinePlayers.Count);
        Assert.Contains("PlayerTwo", vm.OnlinePlayers);

        _runtime.RaiseOutputLine("[12:02:00 INFO]: : PlayerOne left the game");
        Assert.Single(vm.OnlinePlayers);
        Assert.DoesNotContain("PlayerOne", vm.OnlinePlayers);
        Assert.Contains("PlayerTwo", vm.OnlinePlayers);
    }

    [Fact]
    public async Task InitialLoad_ReadsLatestLogHistoryFromDisk()
    {
        string logsDir = Path.Combine(_tempServerDir, "logs");
        Directory.CreateDirectory(logsDir);
        string logFile = Path.Combine(logsDir, "latest.log");

        var utf8NoBom = new UTF8Encoding(false);
        File.WriteAllLines(logFile, ["Line 1", "Line 2", "Line 3", "Line 4", "Line 5"], utf8NoBom);

        using var vm = new ServerMonitorViewModel(_runtime, _logReader, _propertiesStore, "TestServer", NoOpUiService.Instance, _tempServerDir, string.Empty, static () => Task.CompletedTask);

        // 歷史紀錄於背景載入，輪詢直到 Logs 出現內容
        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (vm.Logs.Count < 5 && DateTime.UtcNow < deadline)
        {
            await Task.Delay(20);
        }

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

        var mockUi = new MockMonitorUiService();
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
            static () => Task.CompletedTask);

        // 觸發伺服器就緒事件
        _runtime.RaiseReady();

        for (int i = 0; i < 50 && mockUi.LastNotificationMessage is null; i++)
        {
            await Task.Delay(20);
        }

        Assert.NotNull(mockUi.LastNotificationMessage);
        Assert.Contains("25577", mockUi.LastNotificationMessage);
        Assert.Contains("127.0.0.1", mockUi.LastNotificationMessage);
    }

    [Fact]
    public void LogBurst_UsesBoundedBufferAndTrimsDisplayedLogsAtLowWatermark()
    {
        var mockUi = new MockMonitorUiService();
        using var vm = new ServerMonitorViewModel(
            _runtime,
            _logReader,
            _propertiesStore,
            "TestServer",
            mockUi,
            _tempServerDir,
            string.Empty,
            static () => Task.CompletedTask);

        for (int i = 0; i < 6000; i++)
        {
            _runtime.RaiseOutputLine($"line-{i}");
        }

        mockUi.TickTimers();

        Assert.Equal(1800, vm.Logs.Count);
        Assert.Equal("line-4200", vm.Logs[0]);
        Assert.Equal("line-5999", vm.Logs[^1]);
    }

    private sealed class MockMonitorUiService : NoOpUiService
    {
        private readonly List<ManualUiTimer> _timers = [];

        public string? LastNotificationMessage { get; private set; }
        public string? LastNotificationTitle { get; private set; }
        public NotificationType? LastNotificationType { get; private set; }

        public override IUiTimer CreateUiTimer(TimeSpan interval, Action tick)
        {
            _ = interval;
            var timer = new ManualUiTimer(tick);
            _timers.Add(timer);
            return timer;
        }

        public void TickTimers()
        {
            foreach (ManualUiTimer timer in _timers)
            {
                timer.Tick();
            }
        }

        public override void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info)
        {
            LastNotificationMessage = message;
            LastNotificationTitle = title;
            LastNotificationType = type;
        }

        private sealed class ManualUiTimer(Action tick) : IUiTimer
        {
            public void StartTimer() { }

            public void StopTimer() { }

            public void Tick() => tick();
        }
    }

    private sealed class MockServerRuntime : IServerRuntime
    {
        public int Pid => 1234;
        public bool IsRunning { get; set; }
        public bool IsReady { get; set; }
        public int? ExitCode => 0;
        public string? ActiveServerName => "TestServer";

        public event Action<string>? OutputLineReceived;
        public event Action<int>? ServerExited;
        public event Action? ServerReady;
        public event Action? ServerStarted { add { } remove { } }

        public void RaiseOutputLine(string line) => OutputLineReceived?.Invoke(line);
        public void RaiseExited(int exitCode) => ServerExited?.Invoke(exitCode);
        public void RaiseReady() => ServerReady?.Invoke();

        public Task StartAsync(Core.Servers.ServerLaunchPlan plan, CancellationToken cancellationToken = default)
        {
            _ = plan;
            _ = cancellationToken;
            return Task.CompletedTask;
        }

        public Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default)
        {
            _ = command;
            _ = cancellationToken;
            return Task.FromResult(true);
        }

        public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
        {
            _ = gracefulTimeout;
            _ = cancellationToken;
            return Task.FromResult(new ProcessExitResult(0, false));
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
        public long? GetWorkingSet64() => throw new NotImplementedException();
    }
}
