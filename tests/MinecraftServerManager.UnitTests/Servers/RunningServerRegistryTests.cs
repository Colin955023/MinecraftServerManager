using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class RunningServerRegistryTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-running-registry-");

    public void Dispose() => _temp.Dispose();

    private sealed class FakeInspector : IProcessInspector
    {
        public Dictionary<int, DateTimeOffset> Alive { get; } = [];
        public List<int> Killed { get; } = [];

        public DateTimeOffset? GetStartTimeUtc(int pid) => Alive.TryGetValue(pid, out var t) ? t : null;

        public bool KillProcessTree(int pid)
        {
            Killed.Add(pid);
            Alive.Remove(pid);
            return true;
        }
    }

    private string FilePath => Path.Combine(_temp.FullName, "running_servers.json");

    // 登記與移除為背景寫入，以條件等待檔案內容符合預期
    private async Task<string> WaitForFileAsync(Func<string, bool> predicate)
    {
        string latest = string.Empty;
        await TestWait.UntilAsync(() =>
        {
            if (!File.Exists(FilePath))
            {
                return false;
            }

            try
            {
                latest = File.ReadAllText(FilePath);
                return predicate(latest);
            }
            catch (IOException)
            {
                return false;
            }
        }, "RunningServerRegistry 寫入磁碟完成");
        return latest;
    }

    [Fact]
    public async Task Record_WritesEntry_AndRemoveDeletesIt()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTimeOffset.UtcNow;
        var registry = new RunningServerRegistry(_temp.FullName, inspector);

        registry.Record("Alpha", 100);
        string written = await WaitForFileAsync(static t => t.Contains("Alpha", StringComparison.Ordinal));
        Assert.Contains("Alpha", written, StringComparison.Ordinal);

        registry.Remove("Alpha");
        string after = await WaitForFileAsync(static t => !t.Contains("Alpha", StringComparison.Ordinal));
        Assert.DoesNotContain("Alpha", after, StringComparison.Ordinal);
    }

    [Fact]
    public async Task FlushAsync_QueuedWrites_WaitsForCompletion()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTimeOffset.UtcNow;
        var registry = new RunningServerRegistry(_temp.FullName, inspector);

        registry.Record("Alpha", 100);
        await registry.FlushAsync();
        Assert.Contains("Alpha", File.ReadAllText(FilePath), StringComparison.Ordinal);

        registry.Remove("Alpha");
        await registry.FlushAsync();
        Assert.DoesNotContain("Alpha", File.ReadAllText(FilePath), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Record_WhenStartTimeUnavailable_DoesNotWrite()
    {
        var registry = new RunningServerRegistry(_temp.FullName, new FakeInspector());

        registry.Record("Ghost", 999);
        await registry.FlushAsync();

        Assert.False(File.Exists(FilePath));
    }

    [Fact]
    public async Task FindOrphans_MixedEntries_ReturnsAliveAndPurgesDead()
    {
        var inspector = new FakeInspector();
        var start = DateTimeOffset.UtcNow;
        inspector.Alive[100] = start;
        inspector.Alive[200] = start;
        var previous = new RunningServerRegistry(_temp.FullName, inspector);
        previous.Record("Alive", 100);
        previous.Record("Dead", 200);
        await WaitForFileAsync(static t => t.Contains("Alive", StringComparison.Ordinal) && t.Contains("Dead", StringComparison.Ordinal));
        inspector.Alive.Remove(200);

        var current = new RunningServerRegistry(_temp.FullName, inspector);
        var orphans = await current.FindOrphansAsync(TestContext.Current.CancellationToken);

        var orphan = Assert.Single(orphans);
        Assert.Equal("Alive", orphan.ServerName);
        Assert.DoesNotContain("Dead", File.ReadAllText(FilePath), StringComparison.Ordinal);
    }

    [Fact]
    public async Task FindOrphans_SamePidDifferentStartTime_IsNotOrphan()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTimeOffset.UtcNow;
        var previous = new RunningServerRegistry(_temp.FullName, inspector);
        previous.Record("Reused", 100);
        await WaitForFileAsync(static t => t.Contains("Reused", StringComparison.Ordinal));
        inspector.Alive[100] = DateTimeOffset.UtcNow.AddHours(1);

        var orphans = await new RunningServerRegistry(_temp.FullName, inspector).FindOrphansAsync(TestContext.Current.CancellationToken);

        Assert.Empty(orphans);
    }

    [Fact]
    public async Task FindOrphans_CurrentSessionEntry_Excludes()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTimeOffset.UtcNow;
        var registry = new RunningServerRegistry(_temp.FullName, inspector);
        registry.Record("Mine", 100);
        await WaitForFileAsync(static t => t.Contains("Mine", StringComparison.Ordinal));

        Assert.Empty(await registry.FindOrphansAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Terminate_RegisteredEntry_KillsTreeAndRemoves()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTimeOffset.UtcNow;
        new RunningServerRegistry(_temp.FullName, inspector).Record("Alpha", 100);
        await WaitForFileAsync(static t => t.Contains("Alpha", StringComparison.Ordinal));
        var current = new RunningServerRegistry(_temp.FullName, inspector);
        var orphan = Assert.Single(await current.FindOrphansAsync(TestContext.Current.CancellationToken));

        bool ok = await current.TerminateAsync(orphan, TestContext.Current.CancellationToken);

        Assert.True(ok);
        Assert.Equal([100], inspector.Killed);
        Assert.DoesNotContain("Alpha", File.ReadAllText(FilePath), StringComparison.Ordinal);
    }
}
