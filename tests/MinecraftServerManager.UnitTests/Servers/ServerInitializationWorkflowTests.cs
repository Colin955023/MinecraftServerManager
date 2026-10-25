using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerInitializationWorkflowTests
{
    private sealed class FakeServerRuntime : IServerRuntime
    {
        public int Pid => 1234;
        public bool IsRunning { get; set; } = true;
        public bool IsReady { get; set; }
        public int? ExitCode => null;
        public string? ActiveServerName => "TestServer";
        public bool ShouldThrowOnStop { get; set; }
        public int StopCallCount { get; private set; }

        public event Action<string>? OutputLineReceived { add { } remove { } }
        public event Action? ServerStarted { add { } remove { } }
        public event Action? ServerReady;
        public event Action<int>? ServerExited { add { } remove { } }

        public void TriggerReady() => ServerReady?.Invoke();

        public long? GetWorkingSet64() => null;

        public Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default) => Task.CompletedTask;

        public Task StartAsync(
            string javaExecutablePath,
            string serverDirectory,
            string executableName,
            int memoryMaxMb,
            int? memoryMinMb = null,
            IReadOnlyList<string>? customJvmArgs = null,
            CancellationToken cancellationToken = default) => Task.CompletedTask;

        public Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default) => Task.FromResult(true);

        public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
        {
            StopCallCount++;
            if (ShouldThrowOnStop)
            {
                throw new InvalidOperationException("停止伺服器失敗 (測試用例外)");
            }
            IsRunning = false;
            return Task.FromResult(new ProcessExitResult(0, false));
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    [Fact]
    public async Task WhenServerReadyFires_MarksReadyDetectedAndCallsStop()
    {
        var fakeRuntime = new FakeServerRuntime();
        using var workflow = new ServerInitializationWorkflow(fakeRuntime);

        Assert.False(workflow.ReadyDetected);

        fakeRuntime.TriggerReady();

        for (int i = 0; i < 20 && fakeRuntime.StopCallCount == 0; i++)
        {
            await Task.Delay(25);
        }

        Assert.True(workflow.ReadyDetected);
        Assert.True(fakeRuntime.StopCallCount > 0);
    }

    [Fact]
    public async Task WhenServerReadyFires_AndStopThrows_SwallowsExceptionSafely()
    {
        var fakeRuntime = new FakeServerRuntime { ShouldThrowOnStop = true };
        using var workflow = new ServerInitializationWorkflow(fakeRuntime);

        fakeRuntime.TriggerReady();

        for (int i = 0; i < 20 && fakeRuntime.StopCallCount == 0; i++)
        {
            await Task.Delay(25);
        }

        Assert.True(workflow.ReadyDetected);
        Assert.True(fakeRuntime.StopCallCount > 0);
    }

    [Fact]
    public void Dispose_UnsubscribesFromEvents()
    {
        var fakeRuntime = new FakeServerRuntime();
        var workflow = new ServerInitializationWorkflow(fakeRuntime);
        workflow.Dispose();

        fakeRuntime.TriggerReady();

        Assert.False(workflow.ReadyDetected);
        Assert.Equal(0, fakeRuntime.StopCallCount);
    }
}
