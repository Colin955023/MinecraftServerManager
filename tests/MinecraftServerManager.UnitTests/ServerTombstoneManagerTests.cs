using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerTombstoneManagerTests
{
    [Fact]
    public void MoveWithinStrictEnforcesDirectSubdirectoryAndRejectsExistingDestination()
    {
        var tempDir = Directory.CreateTempSubdirectory("msm-strict-move-");
        try
        {
            string source = Path.Combine(tempDir.FullName, "server1");
            string dest = Path.Combine(tempDir.FullName, "server2");
            Directory.CreateDirectory(source);
            File.WriteAllText(Path.Combine(source, "server.properties"), "motd=test");

            // 成功嚴格移動
            SafeFileSystem.MoveWithinStrict(tempDir.FullName, source, dest);
            Assert.False(Directory.Exists(source));
            Assert.True(Directory.Exists(dest));

            // 目標已存在時拋出例外
            Directory.CreateDirectory(source);
            Assert.Throws<SafeFileSystemException>(() =>
                SafeFileSystem.MoveWithinStrict(tempDir.FullName, source, dest));
        }
        finally
        {
            tempDir.Delete(true);
        }
    }

    [Fact]
    public void CopyWithinRejectsBoundaryViolationAndCopiesDirectoryTree()
    {
        var tempDir = Directory.CreateTempSubdirectory("msm-copy-within-");
        try
        {
            string srcDir = Path.Combine(tempDir.FullName, "src");
            string dstDir = Path.Combine(tempDir.FullName, "dst");
            Directory.CreateDirectory(Path.Combine(srcDir, "mods"));
            File.WriteAllText(Path.Combine(srcDir, "mods", "test.jar"), "dummy jar");

            // 成功複製目錄樹
            bool result = SafeFileSystem.CopyWithin(tempDir.FullName, srcDir, dstDir);
            Assert.True(result);
            Assert.True(File.Exists(Path.Combine(dstDir, "mods", "test.jar")));

            // 超出邊界時拒絕
            string outside = Path.Combine(Path.GetTempPath(), "outside-copy.bin");
            File.WriteAllText(outside, "outside");
            try
            {
                Assert.False(SafeFileSystem.CopyWithin(tempDir.FullName, outside, Path.Combine(tempDir.FullName, "in.bin")));
            }
            finally
            {
                if (File.Exists(outside))
                {
                    File.Delete(outside);
                }
            }
        }
        finally
        {
            tempDir.Delete(true);
        }
    }

    [Fact]
    public void PrepareDeleteTombstoneCreatesMarkerAndJournal()
    {
        var tempDir = Directory.CreateTempSubdirectory("msm-tombstone-prep-");
        try
        {
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
        finally
        {
            tempDir.Delete(true);
        }
    }

    [Fact]
    public void RecoverDeleteTombstonesRestoresUncommittedServer()
    {
        var tempDir = Directory.CreateTempSubdirectory("msm-tombstone-recover-");
        try
        {
            string originalPath = Path.Combine(tempDir.FullName, "UncommittedServer");
            Directory.CreateDirectory(originalPath);
            File.WriteAllText(Path.Combine(originalPath, "config.txt"), "hello");

            var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(
                tempDir.FullName, "UncommittedServer", originalPath);

            bool recovered = false;
            // registeredServerLookup 回傳原路徑，代表伺服器尚未提交刪除
            ServerTombstoneManager.RecoverDeleteTombstones(
                tempDir.FullName,
                name => name == "UncommittedServer" ? originalPath : null,
                onRecovered: name => recovered = true);

            Assert.True(recovered);
            Assert.True(Directory.Exists(originalPath));
            Assert.False(Directory.Exists(tombstonePath));
            Assert.False(File.Exists(journalPath));
            Assert.Equal("hello", File.ReadAllText(Path.Combine(originalPath, "config.txt")));
        }
        finally
        {
            tempDir.Delete(true);
        }
    }

    [Fact]
    public void RecoverDeleteTombstonesCleansCommittedDeletedServer()
    {
        var tempDir = Directory.CreateTempSubdirectory("msm-tombstone-clean-");
        try
        {
            string originalPath = Path.Combine(tempDir.FullName, "CommittedServer");
            Directory.CreateDirectory(originalPath);

            var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(
                tempDir.FullName, "CommittedServer", originalPath);

            bool cleaned = false;
            // registeredServerLookup 回傳 null，代表伺服器已在設定中刪除
            ServerTombstoneManager.RecoverDeleteTombstones(
                tempDir.FullName,
                name => null,
                onCleaned: name => cleaned = true);

            Assert.True(cleaned);
            Assert.False(Directory.Exists(tombstonePath));
            Assert.False(File.Exists(journalPath));
        }
        finally
        {
            tempDir.Delete(true);
        }
    }

    [Fact]
    public void RestoreTransactionRecoveryRestoresMissingServerDirectory()
    {
        var tempDir = Directory.CreateTempSubdirectory("msm-restore-recover-");
        try
        {
            string serverPath = Path.Combine(tempDir.FullName, "MyServer");
            string rollbackDir = Path.Combine(tempDir.FullName, ".MyServer.restore-rollback-12345");
            string journalFile = Path.Combine(tempDir.FullName, ".MyServer.restore-rollback-12345.json");

            Directory.CreateDirectory(rollbackDir);
            File.WriteAllText(Path.Combine(rollbackDir, "restored.txt"), "recovered data");

            var record = new RestoreTransactionRecord("MyServer", serverPath, Path.Combine(tempDir.FullName, "prep"));
            File.WriteAllText(journalFile, JsonCodec.Serialize(record));

            bool recovered = false;
            RestoreTransactionRecovery.RecoverRestoreTransactions(
                [("MyServer", serverPath)],
                onRecovered: name => recovered = true);

            Assert.True(recovered);
            Assert.True(Directory.Exists(serverPath));
            Assert.False(Directory.Exists(rollbackDir));
            Assert.False(File.Exists(journalFile));
            Assert.Equal("recovered data", File.ReadAllText(Path.Combine(serverPath, "restored.txt")));
        }
        finally
        {
            tempDir.Delete(true);
        }
    }
}
