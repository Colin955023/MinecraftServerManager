using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServersRootRelocatorTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-relocator-");

    public void Dispose() => _temp.Dispose();

    private string Root(string name) => Path.Combine(_temp.FullName, name);

    private static string ToJson(string path) => "\"" + path.Replace("\\", "\\\\") + "\"";

    [Fact]
    public void ValidateTargetRoot_EmptyOrFileTarget_Rejects()
    {
        string file = Path.Combine(_temp.FullName, "servers");
        File.WriteAllText(file, "x");

        Assert.Equal(RelocationPathCheckResult.EmptyTarget, ServersRootRelocator.ValidateTargetRoot(Root("old"), "  ", out _, out _));
        Assert.Equal(RelocationPathCheckResult.TargetIsFile, ServersRootRelocator.ValidateTargetRoot(Root("old"), _temp.FullName, out _, out _));
    }

    [Fact]
    public void HasStoredContent_MissingOrEmpty_ReturnsFalse()
    {
        Assert.False(ServersRootRelocator.HasStoredContent(Root("missing")));

        string empty = Root("empty");
        Directory.CreateDirectory(empty);
        Assert.False(ServersRootRelocator.HasStoredContent(empty));

        File.WriteAllText(Path.Combine(empty, ServerDefaults.RegistryFileName), "{}");
        Assert.False(ServersRootRelocator.HasStoredContent(empty));
    }

    [Fact]
    public void HasStoredContent_ServersOrFiles_ReturnsTrue()
    {
        string withServers = Root("with-servers");
        Directory.CreateDirectory(withServers);
        File.WriteAllText(
            Path.Combine(withServers, ServerDefaults.RegistryFileName),
            """{"A":{"name":"A","minecraftVersion":"1.21.4","loaderType":"Vanilla","loaderVersion":"","memoryMaxMb":1024,"memoryMinMb":null,"path":"x","jvmArgs":[],"backupPath":""}}""");
        Assert.True(ServersRootRelocator.HasStoredContent(withServers));

        string withFile = Root("with-file");
        Directory.CreateDirectory(withFile);
        File.WriteAllText(Path.Combine(withFile, "notes.txt"), "x");
        Assert.True(ServersRootRelocator.HasStoredContent(withFile));
    }

    [Fact]
    public void IsTargetDirectoryEmpty_VariousContents_ReflectsState()
    {
        Assert.True(ServersRootRelocator.IsTargetDirectoryEmpty(Root("not-created")));

        string dir = Root("target");
        Directory.CreateDirectory(dir);
        Assert.True(ServersRootRelocator.IsTargetDirectoryEmpty(dir));

        File.WriteAllText(Path.Combine(dir, "a.txt"), "x");
        Assert.False(ServersRootRelocator.IsTargetDirectoryEmpty(dir));
    }

    [Fact]
    public void RelocateAllContent_ValidTarget_MovesAndRewritesRegistry()
    {
        string oldRoot = Root("old");
        string newRoot = Path.Combine(Root("new"), "servers");
        string serverDir = Path.Combine(oldRoot, "Alpha");
        string backupDir = Path.Combine(oldRoot, "backups", "Alpha");
        Directory.CreateDirectory(serverDir);
        Directory.CreateDirectory(backupDir);
        File.WriteAllText(Path.Combine(serverDir, "world.txt"), "data");
        string registry = """{"Alpha":{"name":"Alpha","minecraftVersion":"1.21.4","loaderType":"Vanilla","loaderVersion":"","memoryMaxMb":1024,"memoryMinMb":null,"path":SERVERDIR,"jvmArgs":[],"backupPath":BACKUPDIR}}"""
            .Replace("SERVERDIR", ToJson(serverDir), StringComparison.Ordinal)
            .Replace("BACKUPDIR", ToJson(backupDir), StringComparison.Ordinal);
        File.WriteAllText(Path.Combine(oldRoot, ServerDefaults.RegistryFileName), registry);
        var reports = new List<int>();

        ServersRootRelocator.RelocateAllContent(oldRoot, newRoot, new SynchronousProgress<(int Percent, string Message)>(r => reports.Add(r.Percent)), TestContext.Current.CancellationToken);

        Assert.Equal("data", File.ReadAllText(Path.Combine(newRoot, "Alpha", "world.txt")));
        Assert.False(Directory.Exists(oldRoot));
        string registryText = File.ReadAllText(Path.Combine(newRoot, ServerDefaults.RegistryFileName));
        Assert.Contains(Path.Combine(newRoot, "Alpha").Replace("\\", "\\\\"), registryText, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(Path.Combine(newRoot, "backups", "Alpha").Replace("\\", "\\\\"), registryText, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(100, reports[^1]);
    }

    [Fact]
    public void RelocateAllContent_WhenSourceCannotBeDeleted_CompletesAndReportsLeftover()
    {
        string oldRoot = Root("old");
        string newRoot = Path.Combine(Root("new"), "servers");
        string serverDir = Path.Combine(oldRoot, "Alpha");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "world.txt"), "data");
        string lockedFile = Path.Combine(serverDir, "locked.txt");
        File.WriteAllText(lockedFile, "locked");
        string registry = """{"Alpha":{"name":"Alpha","minecraftVersion":"1.21.4","loaderType":"Vanilla","loaderVersion":"","memoryMaxMb":1024,"memoryMinMb":null,"path":SERVERDIR,"jvmArgs":[],"backupPath":""}}"""
            .Replace("SERVERDIR", ToJson(serverDir), StringComparison.Ordinal);
        File.WriteAllText(Path.Combine(oldRoot, ServerDefaults.RegistryFileName), registry);

        IReadOnlyList<string> leftovers;
        using (new FileStream(lockedFile, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            // 檔案被占用：目錄無法直接移動，改走複製後刪除，刪除失敗不得讓整個遷移失敗
            leftovers = ServersRootRelocator.RelocateAllContent(oldRoot, newRoot, cancellationToken: TestContext.Current.CancellationToken);
        }

        Assert.Equal(serverDir, Assert.Single(leftovers));
        Assert.Equal("data", File.ReadAllText(Path.Combine(newRoot, "Alpha", "world.txt")));
        Assert.Equal("locked", File.ReadAllText(Path.Combine(newRoot, "Alpha", "locked.txt")));
        Assert.True(File.Exists(lockedFile));
        string registryText = File.ReadAllText(Path.Combine(newRoot, ServerDefaults.RegistryFileName));
        Assert.Contains(Path.Combine(newRoot, "Alpha").Replace("\\", "\\\\"), registryText, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void RelocateAllContent_WhenLaterItemCanceledAfterLeftover_RestoresDeletedFilesToSource()
    {
        string oldRoot = Root("old");
        string newRoot = Path.Combine(Root("new"), "servers");
        string alpha = Path.Combine(oldRoot, "Alpha");
        string lockedFile = Path.Combine(alpha, "z-sub", "locked.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(lockedFile)!);
        File.WriteAllText(Path.Combine(alpha, "world.txt"), "data");
        File.WriteAllText(lockedFile, "locked");
        Directory.CreateDirectory(Path.Combine(oldRoot, "Beta"));
        File.WriteAllText(Path.Combine(oldRoot, "Beta", "beta.txt"), "beta");
        Directory.CreateDirectory(Path.Combine(oldRoot, "Gamma"));

        using var cts = new CancellationTokenSource();
        int reports = 0;
        var progress = new SynchronousProgress<(int Percent, string Message)>(_ =>
        {
            // 第二次回報時（Alpha 已搬移且原位置殘留）要求取消，下一輪迴圈擲出並觸發復原
            if (++reports == 2)
            {
                cts.Cancel();
            }
        });

        using (new FileStream(lockedFile, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            Assert.Throws<OperationCanceledException>(() => ServersRootRelocator.RelocateAllContent(oldRoot, newRoot, progress, cts.Token));
        }

        Assert.Equal("data", File.ReadAllText(Path.Combine(alpha, "world.txt")));
        Assert.Equal("locked", File.ReadAllText(lockedFile));
        Assert.Equal("beta", File.ReadAllText(Path.Combine(oldRoot, "Beta", "beta.txt")));
        Assert.False(Directory.Exists(Path.Combine(newRoot, "Alpha")));
    }

    [Fact]
    public void RelocateAllContent_NonEmptyTarget_Rejects()
    {
        string oldRoot = Root("old");
        string newRoot = Path.Combine(Root("new"), "servers");
        Directory.CreateDirectory(Path.Combine(oldRoot, "Alpha"));
        Directory.CreateDirectory(newRoot);
        File.WriteAllText(Path.Combine(newRoot, "existing.txt"), "x");

        Assert.Throws<InvalidOperationException>(() => ServersRootRelocator.RelocateAllContent(oldRoot, newRoot, cancellationToken: TestContext.Current.CancellationToken));
        Assert.True(Directory.Exists(Path.Combine(oldRoot, "Alpha")));
    }

    [Fact]
    public void RelocateAllContent_WhenCancelledMidway_RollsBackMovedItems()
    {
        string oldRoot = Root("old");
        string newRoot = Path.Combine(Root("new"), "servers");
        foreach (string name in new[] { "A", "B", "C" })
        {
            Directory.CreateDirectory(Path.Combine(oldRoot, name));
            File.WriteAllText(Path.Combine(oldRoot, name, "f.txt"), name);
        }

        using var cts = new CancellationTokenSource();
        int reports = 0;
        var progress = new SynchronousProgress<(int Percent, string Message)>(_ =>
        {
            // 第二次回報時（已搬移第一個項目）要求取消，下一輪迴圈會擲出並觸發復原
            if (++reports == 2)
            {
                cts.Cancel();
            }
        });

        Assert.Throws<OperationCanceledException>(() => ServersRootRelocator.RelocateAllContent(oldRoot, newRoot, progress, cts.Token));

        foreach (string name in new[] { "A", "B", "C" })
        {
            Assert.Equal(name, File.ReadAllText(Path.Combine(oldRoot, name, "f.txt")));
        }

        // 遷移前不存在的目標資料夾於回滾後一併移除
        Assert.False(Directory.Exists(newRoot));
    }

    [Fact]
    public void RelocateAllContent_WhenRegistryIsCorrupt_RollsBack()
    {
        string oldRoot = Root("old");
        string newRoot = Root("new");
        Directory.CreateDirectory(Path.Combine(oldRoot, "A"));
        File.WriteAllText(Path.Combine(oldRoot, "A", "f.txt"), "A");
        File.WriteAllText(Path.Combine(oldRoot, "servers.json"), "{ not json");

        Assert.Throws<InvalidDataException>(() => ServersRootRelocator.RelocateAllContent(oldRoot, newRoot, cancellationToken: TestContext.Current.CancellationToken));

        Assert.Equal("A", File.ReadAllText(Path.Combine(oldRoot, "A", "f.txt")));
        Assert.True(File.Exists(Path.Combine(oldRoot, "servers.json")));
        Assert.False(Directory.Exists(Path.Combine(newRoot, "servers")));
    }
}
