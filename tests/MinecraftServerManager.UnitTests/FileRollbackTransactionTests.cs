using MinecraftServerManager.Infrastructure.FileSystem;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class FileRollbackTransactionTests
{
    [Fact]
    public void RollbackRestoresExistingFile()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string source = Path.Combine(root, "staging.txt");
            string target = Path.Combine(root, "target.txt");
            File.WriteAllText(source, "new");
            File.WriteAllText(target, "old");

            using var transaction = new FileRollbackTransaction(root);
            transaction.ReplaceFile(source, target);
            transaction.Rollback();

            Assert.Equal("old", File.ReadAllText(target));
            Assert.False(File.Exists(source));
            Assert.Empty(Directory.GetDirectories(root, ".msm-rollback-*"));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void RollbackRemovesNewFileWhenTargetDidNotExist()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string source = Path.Combine(root, "staging.txt");
            string target = Path.Combine(root, "new.txt");
            File.WriteAllText(source, "new");

            using var transaction = new FileRollbackTransaction(root);
            transaction.ReplaceFile(source, target);
            transaction.Rollback();

            Assert.False(File.Exists(source));
            Assert.False(File.Exists(target));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void CommitKeepsReplacementAndRemovesJournal()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string source = Path.Combine(root, "staging.txt");
            string target = Path.Combine(root, "target.txt");
            File.WriteAllText(source, "new");

            using (var transaction = new FileRollbackTransaction(root))
            {
                transaction.ReplaceFile(source, target);
                transaction.Commit();
            }

            Assert.Equal("new", File.ReadAllText(target));
            Assert.Empty(Directory.GetDirectories(root, ".msm-rollback-*"));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void ReplacementRejectsSourceOutsideRoot()
    {
        string root = CreateTemporaryDirectory();
        string outside = CreateTemporaryDirectory();
        try
        {
            string source = Path.Combine(outside, "source.txt");
            string target = Path.Combine(root, "target.txt");
            File.WriteAllText(source, "outside");

            using var transaction = new FileRollbackTransaction(root);

            Assert.Throws<SafeFileSystemException>(() => transaction.ReplaceFile(source, target));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
            Directory.Delete(outside, recursive: true);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-rollback-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
