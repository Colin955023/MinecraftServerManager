using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class SafeFileSystemTests
{
    [Theory]
    [InlineData(@"Z:\outside\file.txt")]
    [InlineData(@"\\server\share\file.txt")]
    public void IsPathWithinRejectsTargetsOnDifferentRoot(string target)
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        Assert.False(SafeFileSystem.IsPathWithin(rootTemp.FullName, target, strict: false));
    }

    [Fact]
    public void CreateTempSiblingPathStaysInTargetDirectory()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string tempDir = rootTemp.FullName;
        string target = Path.Combine(tempDir, "settings.json");

        string first = AtomicFileWriter.CreateTempSiblingPath(target);
        string second = AtomicFileWriter.CreateTempSiblingPath(target);

        Assert.Equal(tempDir, Path.GetDirectoryName(first));
        Assert.StartsWith(target + ".", first, StringComparison.Ordinal);
        Assert.EndsWith(AtomicFileWriter.TempFileExtension, first, StringComparison.Ordinal);
        Assert.NotEqual(first, second);
    }

    [Fact]
    public void RecoverDeleteTombstones_CleansStagingDirsAndPreservesRestoreRollbacks()
    {
        using var rootTemp = new TempDirectory("msm-tombstones-");
        string root = rootTemp.FullName;
        string createStaging = Path.Combine(root, $"{ServerDefaults.InternalPrefix}create-staging-123");
        string importStaging = Path.Combine(root, $"{ServerDefaults.InternalPrefix}import-staging-456");
        string restoreStaging = Path.Combine(root, $"{ServerDefaults.InternalPrefix}restore-staging-789");
        string restoreRollback = Path.Combine(root, $"{ServerDefaults.InternalPrefix}restore-rollback-abc");
        string restorePreservedLogs = Path.Combine(root, $"{ServerDefaults.InternalPrefix}restore-preserved-logs-def");
        foreach (string dir in (string[])[createStaging, importStaging, restoreStaging, restoreRollback, restorePreservedLogs])
        {
            Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, "marker.txt"), "data");
        }

        ServerTombstoneManager.RecoverDeleteTombstones(root, static _ => null);

        Assert.False(Directory.Exists(createStaging));
        Assert.False(Directory.Exists(importStaging));
        Assert.False(Directory.Exists(restoreStaging));
        Assert.True(Directory.Exists(restoreRollback));
        Assert.True(Directory.Exists(restorePreservedLogs));
    }

    [Fact]
    public void BoundedDirectoryWalkReturnsFilesAndDirectories()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        Directory.CreateDirectory(Path.Combine(root, "nested"));
        File.WriteAllText(Path.Combine(root, "root.txt"), "root");
        File.WriteAllText(Path.Combine(root, "nested", "child.txt"), "child");

        var entries = SafeFileSystem.EnumerateBoundedTree(root).ToList();

        Assert.Contains(entries, static entry => entry.IsDirectory && entry.FullPath.EndsWith("nested", StringComparison.Ordinal));
        Assert.Contains(entries, static entry => !entry.IsDirectory && entry.FullPath.EndsWith("child.txt", StringComparison.Ordinal));
    }

    [Fact]
    public void DirectoryExistsAcceptsDriveRoot()
    {
        string driveRoot = Path.GetPathRoot(Path.GetTempPath())!;

        Assert.True(SafeFileSystem.DirectoryExists(driveRoot));
    }

    [Fact]
    public void BoundedDirectoryWalkRejectsEntryLimit()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        File.WriteAllText(Path.Combine(root, "one.txt"), "1");
        File.WriteAllText(Path.Combine(root, "two.txt"), "2");

        Assert.Throws<SafeFileSystemException>(() => SafeFileSystem.ListBoundedDirectory(root, maxEntries: 1));
    }

    [Fact]
    public void PathWithinRejectsOutsidePath()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        using var outsideTemp = new TempDirectory("msm-filesystem-");
        string outside = outsideTemp.FullName;
        Assert.True(SafeFileSystem.IsPathWithin(root, Path.Combine(root, "child.txt"), strict: false));
        Assert.False(SafeFileSystem.IsPathWithin(root, outside, strict: false));
    }

    [Fact]
    public void DeleteWithin_DeletesDirectoryContainingReadOnlyFilesSuccessfully()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        string targetDir = Path.Combine(root, "dirWithReadOnly");
        Directory.CreateDirectory(targetDir);
        string readOnlyFile = Path.Combine(targetDir, "readonly.txt");
        File.WriteAllText(readOnlyFile, "protected content");

        // 設為唯讀屬性
        File.SetAttributes(readOnlyFile, FileAttributes.ReadOnly);

        bool deleted = SafeFileSystem.DeleteWithin(root, targetDir);
        Assert.True(deleted);
        Assert.False(Directory.Exists(targetDir));
    }

    [Fact]
    public void DeleteWithin_DeletesNestedReadOnlyHiddenEntriesAndReadOnlyDirectories()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        string targetDir = Path.Combine(root, "outer");
        string nestedDir = Path.Combine(targetDir, "level1", "level2");
        Directory.CreateDirectory(nestedDir);
        string hiddenReadOnly = Path.Combine(nestedDir, "hidden.txt");
        string topReadOnly = Path.Combine(targetDir, "top.txt");
        File.WriteAllText(hiddenReadOnly, "hidden");
        File.WriteAllText(topReadOnly, "top");
        File.SetAttributes(hiddenReadOnly, FileAttributes.ReadOnly | FileAttributes.Hidden);
        File.SetAttributes(topReadOnly, FileAttributes.ReadOnly);
        File.SetAttributes(nestedDir, FileAttributes.Directory | FileAttributes.ReadOnly);

        bool deleted = SafeFileSystem.DeleteWithin(root, targetDir);

        Assert.True(deleted);
        Assert.False(Directory.Exists(targetDir));
    }

    [Fact]
    public void EnumerateBoundedTree_PrunesExcludedDirectories()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        string backupsDir = Path.Combine(root, "backups");
        Directory.CreateDirectory(backupsDir);
        File.WriteAllText(Path.Combine(root, "file.txt"), "normal file");
        File.WriteAllText(Path.Combine(backupsDir, "backup1.zip"), "large backup");
        File.WriteAllText(Path.Combine(backupsDir, "backup2.zip"), "large backup 2");

        var entries = SafeFileSystem.EnumerateBoundedTree(
            root,
            pruneDirectory: static (full, name) => string.Equals(name, "backups", StringComparison.OrdinalIgnoreCase))
            .ToList();

        Assert.Contains(entries, static e => !e.IsDirectory && e.FullPath.EndsWith("file.txt", StringComparison.Ordinal));
        Assert.DoesNotContain(entries, static e => e.FullPath.EndsWith("backup1.zip", StringComparison.Ordinal));
        Assert.DoesNotContain(entries, static e => e.FullPath.EndsWith("backup2.zip", StringComparison.Ordinal));
    }

    [Fact]
    public void EnumerateBoundedTree_PrunesPreventMaxEntriesExceeded()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        string backupsDir = Path.Combine(root, "backups");
        Directory.CreateDirectory(backupsDir);
        File.WriteAllText(Path.Combine(root, "keep1.txt"), "keep");
        File.WriteAllText(Path.Combine(root, "keep2.txt"), "keep");

        // 在 backups 目錄中塞入 10 個檔案
        for (int i = 0; i < 10; i++)
        {
            File.WriteAllText(Path.Combine(backupsDir, $"backup_{i}.zip"), "backup");
        }

        // 若剪枝 backups，只會走訪 2 個檔案 + 1 個資料夾（共 3 個項目），在 maxEntries: 4 下順利通過
        var prunedEntries = SafeFileSystem.EnumerateBoundedTree(
            root,
            maxEntries: 4,
            pruneDirectory: static (full, name) => string.Equals(name, "backups", StringComparison.OrdinalIgnoreCase))
            .ToList();

        Assert.Equal(3, prunedEntries.Count);

        // 若不剪枝，總共有 13 個項目，在 maxEntries: 4 下必定擲出 SafeFileSystemException
        Assert.Throws<SafeFileSystemException>(() =>
            SafeFileSystem.EnumerateBoundedTree(root, maxEntries: 4).ToList());
    }

    [Fact]
    public void HasAnyFile_DetectsMatchesAndEarlyExits()
    {
        using var rootTemp = new TempDirectory("msm-filesystem-");
        string root = rootTemp.FullName;
        string subDir = Path.Combine(root, "sub");
        Directory.CreateDirectory(subDir);
        File.WriteAllText(Path.Combine(subDir, "test.jar"), "dummy");

        Assert.False(SafeFileSystem.HasAnyFile(root, "*.jar", SearchOption.TopDirectoryOnly));
        Assert.True(SafeFileSystem.HasAnyFile(root, "*.jar", SearchOption.AllDirectories));
        Assert.False(SafeFileSystem.HasAnyFile(root, "*.zip", SearchOption.AllDirectories));
        Assert.False(SafeFileSystem.HasAnyFile(Path.Combine(root, "non_existent"), "*.jar"));
    }
}
