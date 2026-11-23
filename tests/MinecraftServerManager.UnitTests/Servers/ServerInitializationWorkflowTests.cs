using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerInitializationWorkflowTests
{
    [Fact]
    public async Task ServerReady_Fired_MarksReadyAndStops()
    {
        var fakeRuntime = new FakeServerRuntime { IsRunning = true };
        using var workflow = new ServerInitializationWorkflow(fakeRuntime, new ServerLaunchPlanner());

        Assert.False(workflow.ReadyDetected);

        fakeRuntime.RaiseReady();

        await TestWait.UntilAsync(() => fakeRuntime.StopCount > 0, "就緒後應呼叫停止");

        Assert.True(workflow.ReadyDetected);
        Assert.True(fakeRuntime.StopCount > 0);
    }

    [Fact]
    public async Task WhenServerReadyFires_AndStopThrows_SwallowsExceptionSafely()
    {
        var fakeRuntime = new FakeServerRuntime { IsRunning = true, ThrowOnStop = true };
        using var workflow = new ServerInitializationWorkflow(fakeRuntime, new ServerLaunchPlanner());

        fakeRuntime.RaiseReady();

        await TestWait.UntilAsync(() => fakeRuntime.StopCount > 0, "就緒後應呼叫停止");

        Assert.True(workflow.ReadyDetected);
        Assert.True(fakeRuntime.StopCount > 0);
    }

    [Fact]
    public void Dispose_AfterStart_UnsubscribesEvents()
    {
        var fakeRuntime = new FakeServerRuntime { IsRunning = true };
        var workflow = new ServerInitializationWorkflow(fakeRuntime, new ServerLaunchPlanner());
        workflow.Dispose();

        fakeRuntime.RaiseReady();

        Assert.False(workflow.ReadyDetected);
        Assert.Equal(0, fakeRuntime.StopCount);
    }
}
