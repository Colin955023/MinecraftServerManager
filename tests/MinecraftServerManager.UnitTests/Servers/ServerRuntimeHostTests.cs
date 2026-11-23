using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerRuntimeHostTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-runtime-host-");

    public void Dispose() => _temp.Dispose();

    private sealed class RecordingRegistry : IRunningServerRegistry
    {
        public List<(string Name, int Pid)> Recorded { get; } = [];
        public List<string> Removed { get; } = [];

        public void Record(string serverName, int pid) => Recorded.Add((serverName, pid));

        public void Remove(string serverName) => Removed.Add(serverName);

        public Task<IReadOnlyList<TrackedServerProcess>> FindOrphansAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<TrackedServerProcess>>([]);

        public Task<bool> TerminateAsync(TrackedServerProcess process, CancellationToken cancellationToken = default) =>
            Task.FromResult(true);

        public Task FlushAsync() => Task.CompletedTask;
    }

    private ServerLaunchPlan CreatePlan(string name)
    {
        string dir = Path.Combine(_temp.FullName, name);
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "server.jar"), "dummy jar");
        return TestServerConfigs.CreatePlan(name, dir);
    }

    [Fact]
    public async Task GetRuntime_SameNameIgnoringCase_ReturnsSameInstance()
    {
        await using var host = new ServerRuntimeHost(new StubProcessRunner(interactive: true), new RecordingRegistry());

        var a = host.GetRuntime("Alpha");
        var b = host.GetRuntime("alpha");
        var c = host.GetRuntime("Beta");

        Assert.Same(a, b);
        Assert.NotSame(a, c);
    }

    [Fact]
    public async Task GetRuntime_TwoServers_RunSimultaneously()
    {
        await using var host = new ServerRuntimeHost(new StubProcessRunner(interactive: true), new RecordingRegistry());

        await host.GetRuntime("Alpha").StartAsync(CreatePlan("Alpha"), TestContext.Current.CancellationToken);
        await host.GetRuntime("Beta").StartAsync(CreatePlan("Beta"), TestContext.Current.CancellationToken);

        Assert.True(host.IsRunning("Alpha"));
        Assert.True(host.IsRunning("beta"));
        Assert.True(host.IsAnyRunning);
        Assert.Equal(["Alpha", "Beta"], host.GetRunningServerNames().Order().ToArray());
    }

    [Fact]
    public async Task ServerStateChanged_ReportsServerName_AndRegistryFollowsLifecycle()
    {
        var registry = new RecordingRegistry();
        await using var host = new ServerRuntimeHost(new StubProcessRunner(interactive: true), registry);
        var changed = new List<string>();
        host.ServerStateChanged += changed.Add;
        var exited = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        host.ServerStateChanged += _ =>
        {
            if (registry.Removed.Count > 0)
            {
                exited.TrySetResult();
            }
        };

        var runtime = host.GetRuntime("Alpha");
        await runtime.StartAsync(CreatePlan("Alpha"), TestContext.Current.CancellationToken);

        Assert.Equal([("Alpha", 1234)], registry.Recorded);
        Assert.Contains("Alpha", changed);

        await runtime.StopAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);
        await exited.Task.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.Equal(["Alpha"], registry.Removed);
        Assert.False(host.IsRunning("Alpha"));
        Assert.False(host.IsAnyRunning);
    }

    [Fact]
    public async Task ReleaseIdleRuntimeAsync_RunningAndStopped_ReleasesOnlyStopped()
    {
        await using var host = new ServerRuntimeHost(new StubProcessRunner(interactive: true), new RecordingRegistry());
        var idle = host.GetRuntime("Idle");
        var running = host.GetRuntime("Running");
        await running.StartAsync(CreatePlan("Running"), TestContext.Current.CancellationToken);

        Assert.True(await host.ReleaseIdleRuntimeAsync("idle"));
        Assert.False(await host.ReleaseIdleRuntimeAsync("Running"));
        Assert.False(await host.ReleaseIdleRuntimeAsync("Missing"));

        Assert.NotSame(idle, host.GetRuntime("Idle"));
        Assert.Same(running, host.GetRuntime("Running"));
    }
}
