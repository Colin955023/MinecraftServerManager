using MinecraftServerManager.Infrastructure.FileSystem;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerTombstoneManagerTests
{
    [Fact]
    public void MoveWithinStrictEnforcesDirectSubdirectoryAndRejectsExistingDestination()
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
    public void PrepareDeleteTombstoneCreatesMarkerAndJournal()
    {
        using var tempDir = new TempDirectory("msm-tombstone-prep-");
        string serverPath = Path.Combine(tempDir.FullName, "Survival");
        Directory.CreateDirectory(serverPath);
        File.WriteAllText(Path.Combine(serverPath, "world.txt"), "data");

        var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(
            tempDir.FullName, "Survival", serverPath);

        Assert.False(Directory.Exists(serverPath));
        Assert.True(Directory.Exists(tombstonePath));
        Assert.True(File.Exists(journalPath));
        Assert.True(File.Exists(Path.Combine(tombstonePath, ServerTombstoneManager.DeleteMarker)));
    }

    [Fact]
    public void RecoverDeleteTombstonesRestoresUncommittedServer()
    {
        using var tempDir = new TempDirectory("msm-tombstone-recover-");
        string originalPath = Path.Combine(tempDir.FullName, "UncommittedServer");
        Directory.CreateDirectory(originalPath);
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
    public void RecoverDeleteTombstonesCleansCommittedDeletedServer()
    {
        using var tempDir = new TempDirectory("msm-tombstone-clean-");
        string originalPath = Path.Combine(tempDir.FullName, "CommittedServer");
        Directory.CreateDirectory(originalPath);

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
