using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.UnitTests.FileSystem;

public sealed class ServerTombstoneManagerTests
{
    [Fact]
    public void MoveWithinStrict_NonDirectChildOrExistingDestination_Rejects()
    {
        using var tempDir = new TempDirectory("msm-strict-move-");
        string source = Path.Combine(tempDir.FullName, "server1");
        string dest = Path.Combine(tempDir.FullName, "server2");
        Directory.CreateDirectory(source);
        File.WriteAllText(Path.Combine(source, "server.properties"), "motd=test");

        // 成功嚴格移動
        SafeFileSystem.MoveWithinStrict(tempDir.FullName, source, dest);
        Assert.False(Directory.Exists(source));
        Assert.True(Directory.Exists(dest));

        // 目標已存在時擲出例外
        Directory.CreateDirectory(source);
        Assert.Throws<SafeFileSystemException>(() =>
            SafeFileSystem.MoveWithinStrict(tempDir.FullName, source, dest));
    }

    [Fact]
    public void PrepareDeleteTombstone_ServerDirectory_CreatesMarkerAndJournal()
    {
        using var tempDir = new TempDirectory("msm-tombstone-prep-");
        string serverPath = tempDir.CreateSubdirectory("Survival");
        File.WriteAllText(Path.Combine(serverPath, "world.txt"), "data");

        var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(
            tempDir.FullName, "Survival", serverPath);

        Assert.False(Directory.Exists(serverPath));
        Assert.True(Directory.Exists(tombstonePath));
        Assert.True(File.Exists(journalPath));
        Assert.True(File.Exists(Path.Combine(tombstonePath, ServerTombstoneManager.DeleteMarker)));
    }

    [Fact]
    public void RecoverDeleteTombstones_Uncommitted_RestoresServer()
    {
        using var tempDir = new TempDirectory("msm-tombstone-recover-");
        string originalPath = tempDir.CreateSubdirectory("UncommittedServer");
        File.WriteAllText(Path.Combine(originalPath, "config.txt"), "hello");

        var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(
            tempDir.FullName, "UncommittedServer", originalPath);

        // registeredServerLookup 回傳原路徑，代表伺服器尚未提交刪除
        ServerTombstoneManager.RecoverDeleteTombstones(
            tempDir.FullName,
            name => name == "UncommittedServer" ? originalPath : null);

        Assert.True(Directory.Exists(originalPath));
        Assert.False(Directory.Exists(tombstonePath));
        Assert.False(File.Exists(journalPath));
        Assert.Equal("hello", File.ReadAllText(Path.Combine(originalPath, "config.txt")));
    }

    [Fact]
    public void RecoverDeleteTombstones_Committed_CleansServer()
    {
        using var tempDir = new TempDirectory("msm-tombstone-clean-");
        string originalPath = tempDir.CreateSubdirectory("CommittedServer");

        var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(
            tempDir.FullName, "CommittedServer", originalPath);

        // registeredServerLookup 回傳 null，代表伺服器已在設定中刪除
        ServerTombstoneManager.RecoverDeleteTombstones(
            tempDir.FullName,
            name => null);

        Assert.False(Directory.Exists(tombstonePath));
        Assert.False(File.Exists(journalPath));
    }
}
