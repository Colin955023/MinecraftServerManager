using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

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
    }

    private ServerLaunchPlan CreatePlan(string name)
    {
        string dir = Path.Combine(_temp.FullName, name);
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "server.jar"), "dummy jar");
        return new ServerLaunchPlanner().CreatePlan(
            new ServerConfig(ServerName.Parse(name), MinecraftVersion.Parse("1.21.4"), LoaderKind.Vanilla, string.Empty, 1024, null, path: dir),
            "server.jar",
            "java.exe");
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
    public async Task TwoServers_CanRunSimultaneously()
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
}
