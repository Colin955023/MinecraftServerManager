using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class RunningServerRegistryTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-running-registry-");

    public void Dispose() => _temp.Dispose();

    private sealed class FakeInspector : IProcessInspector
    {
        public Dictionary<int, DateTime> Alive { get; } = [];
        public List<int> Killed { get; } = [];

        public DateTime? GetStartTimeUtc(int pid) => Alive.TryGetValue(pid, out var t) ? t : null;

        public bool KillProcessTree(int pid)
        {
            Killed.Add(pid);
            Alive.Remove(pid);
            return true;
        }
    }

    private string FilePath => Path.Combine(_temp.FullName, "running_servers.json");

    // 登記與移除為背景寫入，輪詢等待檔案內容符合條件
    private async Task<string> WaitForFileAsync(Func<string, bool> predicate)
    {
        for (int i = 0; i < 200; i++)
        {
            if (File.Exists(FilePath))
            {
                try
                {
                    string text = File.ReadAllText(FilePath);
                    if (predicate(text))
                    {
                        return text;
                    }
                }
                catch (IOException)
                {
                }
            }

            await Task.Delay(25, TestContext.Current.CancellationToken);
        }

        return File.Exists(FilePath) ? File.ReadAllText(FilePath) : string.Empty;
    }

    [Fact]
    public async Task Record_WritesEntry_AndRemoveDeletesIt()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTime.UtcNow;
        var registry = new RunningServerRegistry(_temp.FullName, inspector);

        registry.Record("Alpha", 100);
        string written = await WaitForFileAsync(static t => t.Contains("Alpha", StringComparison.Ordinal));
        Assert.Contains("Alpha", written, StringComparison.Ordinal);

        registry.Remove("Alpha");
        string after = await WaitForFileAsync(static t => !t.Contains("Alpha", StringComparison.Ordinal));
        Assert.DoesNotContain("Alpha", after, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Record_WhenStartTimeUnavailable_DoesNotWrite()
    {
        var registry = new RunningServerRegistry(_temp.FullName, new FakeInspector());

        registry.Record("Ghost", 999);
        await Task.Delay(200, TestContext.Current.CancellationToken);

        Assert.False(File.Exists(FilePath));
    }

    [Fact]
    public async Task FindOrphans_ReturnsAliveEntriesAndPurgesDeadOnes()
    {
        var inspector = new FakeInspector();
        var start = DateTime.UtcNow;
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
        inspector.Alive[100] = DateTime.UtcNow;
        var previous = new RunningServerRegistry(_temp.FullName, inspector);
        previous.Record("Reused", 100);
        await WaitForFileAsync(static t => t.Contains("Reused", StringComparison.Ordinal));
        inspector.Alive[100] = DateTime.UtcNow.AddHours(1);

        var orphans = await new RunningServerRegistry(_temp.FullName, inspector).FindOrphansAsync(TestContext.Current.CancellationToken);

        Assert.Empty(orphans);
    }

    [Fact]
    public async Task FindOrphans_ExcludesEntriesRecordedByCurrentSession()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTime.UtcNow;
        var registry = new RunningServerRegistry(_temp.FullName, inspector);
        registry.Record("Mine", 100);
        await WaitForFileAsync(static t => t.Contains("Mine", StringComparison.Ordinal));

        Assert.Empty(await registry.FindOrphansAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Terminate_KillsProcessTreeAndRemovesEntry()
    {
        var inspector = new FakeInspector();
        inspector.Alive[100] = DateTime.UtcNow;
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
