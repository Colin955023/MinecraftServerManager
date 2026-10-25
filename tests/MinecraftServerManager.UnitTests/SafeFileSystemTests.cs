using MinecraftServerManager.Infrastructure.FileSystem;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class SafeFileSystemTests
{
    [Fact]
    public void BoundedDirectoryWalkReturnsFilesAndDirectories()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            Directory.CreateDirectory(Path.Combine(root, "nested"));
            File.WriteAllText(Path.Combine(root, "root.txt"), "root");
            File.WriteAllText(Path.Combine(root, "nested", "child.txt"), "child");

            var entries = SafeFileSystem.WalkBoundedTree(root);

            Assert.Contains(entries, static entry => entry.IsDirectory && entry.FullPath.EndsWith("nested", StringComparison.Ordinal));
            Assert.Contains(entries, static entry => !entry.IsDirectory && entry.FullPath.EndsWith("child.txt", StringComparison.Ordinal));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void BoundedDirectoryWalkRejectsEntryLimit()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            File.WriteAllText(Path.Combine(root, "one.txt"), "1");
            File.WriteAllText(Path.Combine(root, "two.txt"), "2");

            Assert.Throws<SafeFileSystemException>(() => SafeFileSystem.ListBoundedDirectory(root, maxEntries: 1));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void PathWithinRejectsOutsidePath()
    {
        string root = CreateTemporaryDirectory();
        string outside = CreateTemporaryDirectory();
        try
        {
            Assert.True(SafeFileSystem.IsPathWithin(root, Path.Combine(root, "child.txt"), strict: false));
            Assert.False(SafeFileSystem.IsPathWithin(root, outside, strict: false));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
            Directory.Delete(outside, recursive: true);
        }
    }

    [Fact]
    public void DeleteWithin_DeletesDirectoryContainingReadOnlyFilesSuccessfully()
    {
        string root = CreateTemporaryDirectory();
        try
        {
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
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public void EnumerateBoundedTree_PrunesExcludedDirectories()
    {
        string root = CreateTemporaryDirectory();
        try
        {
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
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public void EnumerateBoundedTree_PrunesPreventMaxEntriesExceeded()
    {
        string root = CreateTemporaryDirectory();
        try
        {
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

            // 若不剪枝，總共有 13 個項目，在 maxEntries: 4 下必定拋出 SafeFileSystemException
            Assert.Throws<SafeFileSystemException>(() =>
                SafeFileSystem.EnumerateBoundedTree(root, maxEntries: 4).ToList());
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-filesystem-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
