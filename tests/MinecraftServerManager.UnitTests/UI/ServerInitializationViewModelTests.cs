using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>初次啟動初始化視窗 ViewModel 測試（啟動檔解析、輸出彙整、就緒判定、倒數關閉與關閉攔截）</summary>
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
        new ServerLaunchPlanner(),
        new ServerConfig(ServerName.Parse("InitServer"), MinecraftVersion.Parse("1.21.4"), LoaderKind.Vanilla, string.Empty, 2048, path: _serverDir),
        "java",
        _ui);

    [Fact]
    public async Task StartAsync_UsesStartScriptWhenPresent()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, ServerDefaults.StartServerBatFileName), "@echo off");
        using var vm = CreateViewModel();

        await vm.StartAsync();

        Assert.NotNull(_runtime.LastPlan);
        Assert.True(_runtime.LastPlan.IsScript);
        Assert.EndsWith(ServerDefaults.StartServerBatFileName, _runtime.LastPlan.JavaExecutable, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("偵測到啟動腳本", vm.ConsoleText, StringComparison.Ordinal);
        Assert.Equal("正在初始化伺服器「InitServer」", vm.TitleText);
    }

    [Fact]
    public async Task StartAsync_FallsBackToServerJar()
    {
        await File.WriteAllTextAsync(Path.Combine(_serverDir, "server.jar"), "dummy jar");
        using var vm = CreateViewModel();

        await vm.StartAsync();

        Assert.NotNull(_runtime.LastPlan);
        Assert.Contains("server.jar", _runtime.LastPlan.Arguments);
        Assert.Contains("nogui", _runtime.LastPlan.Arguments);
    }

    [Fact]
    public async Task OutputLines_FlushIntoConsoleAndUpdateStatus()
    {
        using var vm = CreateViewModel();
        await vm.StartAsync();

        _runtime.RaiseOutputLine("[Server] Preparing level \"world\"");
        _ui.TickRunningTimers();

        Assert.Contains("Preparing level", vm.ConsoleText, StringComparison.Ordinal);
        Assert.Equal("狀態：載入世界中...", vm.StatusText);
    }

    [Fact]
    public async Task ExitAfterReady_MarksSuccessAndClosesAfterCountdown()
    {
        using var vm = CreateViewModel();
        int closeRequests = 0;
        vm.CloseRequested += () => closeRequests++;
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
    public async Task ExitWithoutReady_ShowsWarningCountdownAndCloseButton()
    {
        using var vm = CreateViewModel();
        await vm.StartAsync();

        _runtime.RaiseExited(1);

        Assert.False(vm.IsSuccess);
        Assert.Equal("關閉", vm.CompleteButtonText);
        Assert.Equal(InitializationCountdownState.Warning, vm.CountdownState);
        Assert.Equal(60, vm.CountdownSeconds);
        Assert.Contains("未收到就緒標記", vm.ConsoleText, StringComparison.Ordinal);
    }

    [Fact]
    public async Task HandleClosing_WhileRunning_InterceptsAndStopsServer()
    {
        using var vm = CreateViewModel();
        var closed = new TaskCompletionSource();
        vm.CloseRequested += () => closed.TrySetResult();
        await vm.StartAsync();
        _runtime.IsRunning = true;

        Assert.True(vm.HandleClosing());
        await closed.Task.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.True(_runtime.StopCount >= 1);
        Assert.False(vm.HandleClosing());
        // 僅剩初始化流程自身的 ServerReady 訂閱（於 ViewModel 釋放時解除）
        Assert.Equal(1, _runtime.SubscriberCount);
    }

    [Fact]
    public void CancelAndComplete_SetResultAndRequestClose()
    {
        using var vm = CreateViewModel();
        int closeRequests = 0;
        vm.CloseRequested += () => closeRequests++;

        vm.Complete();
        Assert.True(vm.IsSuccess);
        vm.Cancel();
        Assert.False(vm.IsSuccess);
        Assert.Equal(2, closeRequests);
    }

    [Fact]
    public void Dispose_RemovesAllRuntimeSubscriptions()
    {
        var vm = CreateViewModel();
        vm.Dispose();

        Assert.Equal(0, _runtime.SubscriberCount);
    }

    [Fact]
    public void AppendWithLimit_TrimsToTailWhenExceedingMaximum()
    {
        string current = new('a', ServerInitializationViewModel.MaxConsoleChars);

        string result = ServerInitializationViewModel.AppendWithLimit(current, "END");

        Assert.Equal(ServerInitializationViewModel.TrimmedConsoleChars + 3, result.Length);
        Assert.EndsWith("END", result, StringComparison.Ordinal);
        Assert.Equal("abc", ServerInitializationViewModel.AppendWithLimit("ab", "c"));
    }

    [Theory]
    [InlineData("Loading dimension minecraft:overworld", "狀態：準備世界與生成區域中...")]
    [InlineData("Preparing spawn area: 50%", "狀態：準備世界與生成區域中...")]
    [InlineData("Preparing level \"world\"", "狀態：載入世界中...")]
    [InlineData("Done (3.2s)!", null)]
    public void DetectStatus_MapsKnownMarkers(string line, string? expected) => Assert.Equal(expected, ServerInitializationViewModel.DetectStatus(line));
}
