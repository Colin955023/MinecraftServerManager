using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerInitializationViewModelTests : IDisposable
{
    private readonly TempDirectory _serverDirTemp = new("msm-init-vm-");
    private readonly string _serverDir;
    private readonly FakeServerRuntime _runtime = new();
    private readonly ManualUiService _ui = new();

    public ServerInitializationViewModelTests()
    {
        _serverDir = _serverDirTemp.FullName;
    }

    public void Dispose() => _serverDirTemp.Dispose();

    private ServerInitializationViewModel CreateViewModel() => new(
        _runtime,
        new ServerInitializationWorkflow(_runtime, new ServerLaunchPlanner()),
        new ServerConfig(ServerName.Parse("InitServer"), MinecraftVersion.Parse("1.21.4"), LoaderKind.Vanilla, string.Empty, 2048, path: _serverDir),
        "java",
        _ui);

    [Fact]
    public async Task StartAsync_StartScriptPresent_UsesScript()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, ServerDefaults.StartServerBatFileName), "@echo off", TestContext.Current.CancellationToken);
        using var vm = CreateViewModel();

        await vm.StartAsync();

        Assert.NotNull(_runtime.LastPlan);
        Assert.True(_runtime.LastPlan.IsScript);
        Assert.EndsWith(ServerDefaults.StartServerBatFileName, _runtime.LastPlan.JavaExecutable, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("偵測到啟動腳本", string.Join('\n', vm.ConsoleLines), StringComparison.Ordinal);
        Assert.Equal("正在初始化伺服器「InitServer」", vm.TitleText);
    }

    [Fact]
    public async Task StartAsync_NoStartScript_UsesServerJar()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy jar", TestContext.Current.CancellationToken);
        using var vm = CreateViewModel();

        await vm.StartAsync();

        Assert.NotNull(_runtime.LastPlan);
        Assert.Contains("server.jar", _runtime.LastPlan.Arguments);
        Assert.Contains("nogui", _runtime.LastPlan.Arguments);
    }

    [Fact]
    public async Task OutputLines_Received_FlushesConsoleAndUpdatesStatus()
    {
        using var vm = CreateViewModel();
        await vm.StartAsync();

        _runtime.RaiseOutputLine("[Server] Preparing level \"world\"");
        _ui.TickRunningTimers();

        Assert.Contains("Preparing level", string.Join('\n', vm.ConsoleLines), StringComparison.Ordinal);
        Assert.Equal("狀態：載入世界中...", vm.StatusText);
    }

    [Fact]
    public async Task ServerExit_AfterReady_MarksSuccessAndCloses()
    {
        using var vm = CreateViewModel();
        int closeRequests = 0;
        vm.RequestClose += _ => closeRequests++;
        await vm.StartAsync();

        _runtime.RaiseReady();
        _runtime.RaiseExited(0);

        Assert.True(vm.IsSuccess);
        Assert.False(vm.IsProgressVisible);
        Assert.True(vm.IsCompleteEnabled);
        Assert.Equal("完成初始化", vm.CompleteButtonText);
        Assert.Equal(InitializationCountdownState.Success, vm.CountdownState);
        Assert.Equal(2, vm.CountdownSeconds);

        _ui.TickRunningTimers();
        _ui.TickRunningTimers();

        Assert.Equal(1, closeRequests);
        Assert.False(vm.HandleClosing());
    }

    [Fact]
    public async Task ServerExit_BeforeReady_ShowsWarningAndCloseButton()
    {
        using var vm = CreateViewModel();
        await vm.StartAsync();

        _runtime.RaiseExited(1);

        Assert.False(vm.IsSuccess);
        Assert.Equal("關閉", vm.CompleteButtonText);
        Assert.Equal(InitializationCountdownState.Warning, vm.CountdownState);
        Assert.Equal(60, vm.CountdownSeconds);
        Assert.Contains("未收到就緒標記", string.Join('\n', vm.ConsoleLines), StringComparison.Ordinal);
    }

    [Fact]
    public async Task HandleClosing_WhileRunning_InterceptsAndStopsServer()
    {
        using var vm = CreateViewModel();
        var closed = new TaskCompletionSource();
        vm.RequestClose += _ => closed.TrySetResult();
        await vm.StartAsync();
        _runtime.IsRunning = true;

        Assert.True(vm.HandleClosing());
        await closed.Task.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.True(_runtime.StopCount >= 1);
        Assert.False(vm.HandleClosing());
        // 僅剩初始化流程自身的 ServerReady 訂閱（於 ViewModel 釋放時解除）
        Assert.Equal(1, _runtime.SubscriberCount);
    }

    [Fact]
    public void CancelAndComplete_Invoked_SetResultAndRequestClose()
    {
        using var vm = CreateViewModel();
        int closeRequests = 0;
        vm.RequestClose += _ => closeRequests++;

        vm.Complete();
        Assert.True(vm.IsSuccess);
        vm.Cancel();
        Assert.False(vm.IsSuccess);
        Assert.Equal(2, closeRequests);
    }

    [Fact]
    public void Dispose_AfterStart_RemovesRuntimeSubscriptions()
    {
        var vm = CreateViewModel();
        vm.Dispose();

        Assert.Equal(0, _runtime.SubscriberCount);
    }

    [Fact]
    public async Task ConsoleLines_ExceedsMaximum_TrimsToTail()
    {
        using var vm = CreateViewModel();
        await vm.StartAsync();

        for (int i = 0; i <= ServerInitializationViewModel.MaxConsoleLines; i++)
        {
            _runtime.RaiseOutputLine($"line {i}");
            if (i % 400 == 0)
            {
                vm.FlushPendingLines();
            }
        }

        vm.FlushPendingLines();

        Assert.True(vm.ConsoleLines.Count <= ServerInitializationViewModel.MaxConsoleLines);
        Assert.Equal($"line {ServerInitializationViewModel.MaxConsoleLines}", vm.ConsoleLines[^1]);
    }

    [Fact]
    public async Task RuntimeCallbacks_AfterDispose_AreIgnored()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy jar", TestContext.Current.CancellationToken);
        var vm = CreateViewModel();
        await vm.StartAsync();
        int lines = vm.ConsoleLines.Count;
        vm.Dispose();

        vm.HandleServerExited(0);
        vm.FlushPendingLines();

        Assert.Equal(lines, vm.ConsoleLines.Count);
        Assert.True(vm.IsProgressVisible);
        Assert.Equal(InitializationCountdownState.None, vm.CountdownState);
    }

    [Theory]
    [InlineData("Loading dimension minecraft:overworld", "狀態：準備世界與生成區域中...")]
    [InlineData("Preparing spawn area: 50%", "狀態：準備世界與生成區域中...")]
    [InlineData("Preparing level \"world\"", "狀態：載入世界中...")]
    [InlineData("Done (3.2s)!", null)]
    public void DetectStatus_KnownMarker_MapsStatus(string line, string? expected) => Assert.Equal(expected, ServerInitializationViewModel.DetectStatus(line));
}
