using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerStopCoordinatorTests : IAsyncDisposable
{
    private readonly FakeServerRuntimeHost _host = new();

    public ValueTask DisposeAsync() => _host.DisposeAsync();
    private readonly ManualUiService _ui = new();

    private ServerStopCoordinator CreateCoordinator() => new(_ui, _host);

    private static ProcessExitResult Exited() => new(0, false);

    [Fact]
    public async Task StopAsync_WhenNotRunning_ReturnsTrueWithoutSendingCommand()
    {
        var runtime = _host.GetFake("A");

        bool result = await CreateCoordinator().StopAsync("A");

        Assert.True(result);
        Assert.Empty(runtime.SentCommands);
        Assert.Empty(_ui.Notifications);
    }

    [Fact]
    public async Task StopAsync_WhenStopsWithinTimeout_SendsStopAndNotifiesSuccess()
    {
        var runtime = _host.GetFake("A");
        runtime.IsRunning = true;
        runtime.WaitResults.Enqueue(Exited());

        bool result = await CreateCoordinator().StopAsync("A");

        Assert.True(result);
        Assert.Equal(["stop"], runtime.SentCommands);
        Assert.Empty(_ui.ChoiceMessages);
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Success);
    }

    [Fact]
    public async Task StopAsync_WhenTimeoutThenKeepWaiting_StopsWithoutForceKill()
    {
        var runtime = _host.GetFake("A");
        runtime.IsRunning = true;
        runtime.WaitResults.Enqueue(null);
        runtime.WaitResults.Enqueue(Exited());
        _ui.ChoiceResults.Enqueue(false);

        bool result = await CreateCoordinator().StopAsync("A");

        Assert.True(result);
        Assert.Single(_ui.ChoiceMessages);
        Assert.Equal("強制終止", _ui.ChoiceMessages[0].PrimaryText);
        Assert.Equal(0, runtime.StopCount);
        Assert.Equal(1, _ui.ActivateMainWindowCount);
    }

    [Fact]
    public async Task StopAsync_WhenTimeoutThenForce_ForceKillsAndWarns()
    {
        var runtime = _host.GetFake("A");
        runtime.IsRunning = true;
        runtime.WaitResults.Enqueue(null);
        _ui.ChoiceResults.Enqueue(true);

        bool result = await CreateCoordinator().StopAsync("A");

        Assert.True(result);
        Assert.Equal(1, runtime.StopCount);
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("強制終止", StringComparison.Ordinal));
    }

    [Fact]
    public async Task StopAsync_WhenCalledTwiceConcurrently_SecondCallNotifiesAndReturnsFalse()
    {
        var runtime = _host.GetFake("A");
        runtime.IsRunning = true;
        runtime.WaitResults.Enqueue(null);
        _ui.ChoiceGate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var coordinator = CreateCoordinator();

        var first = coordinator.StopAsync("A");
        Assert.True(coordinator.IsStopping("A"));

        bool second = await coordinator.StopAsync("A");

        Assert.False(second);
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Info && n.Message.Contains("停止中", StringComparison.Ordinal));

        _ui.ChoiceGate.SetResult(true);
        Assert.True(await first);
        Assert.False(coordinator.IsStopping("A"));
    }

    [Fact]
    public async Task StopAllForShutdownAsync_WhenNoneRunning_ReturnsTrueWithoutAsking()
    {
        bool result = await CreateCoordinator().StopAllForShutdownAsync();

        Assert.True(result);
        Assert.Empty(_ui.ChoiceMessages);
    }

    [Fact]
    public async Task StopAllForShutdownAsync_WhenUserCancels_ReturnsFalseAndSendsNothing()
    {
        var runtime = _host.GetFake("A");
        runtime.IsRunning = true;
        _ui.ChoiceResults.Enqueue(false);

        bool result = await CreateCoordinator().StopAllForShutdownAsync();

        Assert.False(result);
        Assert.Empty(runtime.SentCommands);
    }

    [Fact]
    public async Task StopAllForShutdownAsync_WhenAllStopInTime_ReturnsTrue()
    {
        var a = _host.GetFake("A");
        var b = _host.GetFake("B");
        a.IsRunning = true;
        b.IsRunning = true;
        a.WaitResults.Enqueue(Exited());
        b.WaitResults.Enqueue(Exited());
        _ui.ChoiceResults.Enqueue(true);

        bool result = await CreateCoordinator().StopAllForShutdownAsync();

        Assert.True(result);
        Assert.Equal(["stop"], a.SentCommands);
        Assert.Equal(["stop"], b.SentCommands);
        Assert.Single(_ui.ChoiceMessages);
        Assert.Equal(0, a.StopCount + b.StopCount);
    }

    [Fact]
    public async Task StopAllForShutdownAsync_WhenOneTimesOutAndForced_ForceKillsOnlyThatServer()
    {
        var a = _host.GetFake("A");
        var b = _host.GetFake("B");
        a.IsRunning = true;
        b.IsRunning = true;
        a.WaitResults.Enqueue(Exited());
        b.WaitResults.Enqueue(null);
        _ui.ChoiceResults.Enqueue(true);
        _ui.ChoiceResults.Enqueue(true);

        bool result = await CreateCoordinator().StopAllForShutdownAsync();

        Assert.True(result);
        Assert.Equal(0, a.StopCount);
        Assert.Equal(1, b.StopCount);
    }
}
