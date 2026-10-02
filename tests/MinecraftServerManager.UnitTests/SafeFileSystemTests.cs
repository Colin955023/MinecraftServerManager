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

            Assert.Contains(entries, entry => entry.IsDirectory && entry.FullPath.EndsWith("nested", StringComparison.Ordinal));
            Assert.Contains(entries, entry => !entry.IsDirectory && entry.FullPath.EndsWith("child.txt", StringComparison.Ordinal));
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

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-filesystem-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
