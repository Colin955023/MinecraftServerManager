using System.IO.Compression;
using MinecraftServerManager.Infrastructure.FileSystem;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class SafeZipArchiveTests
{
    [Fact]
    public void ExtractPreservesFilesAndReportsProgress()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string archivePath = Path.Combine(root, "sample.zip");
            string destination = Path.Combine(root, "extract");
            CreateArchive(archivePath, ("nested/file.txt", "內容"));
            var progress = new List<(long Current, long Total)>();

            SafeZipArchive.Extract(archivePath, destination, (current, total) => progress.Add((current, total)));

            Assert.Equal("內容", File.ReadAllText(Path.Combine(destination, "nested", "file.txt")));
            Assert.NotEmpty(progress);
            Assert.Equal(progress[^1].Total, progress[^1].Current);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void ExtractRejectsTraversalMember()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string archivePath = Path.Combine(root, "unsafe.zip");
            using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
            {
                using var writer = new StreamWriter(archive.CreateEntry("../outside.txt").Open());
                writer.Write("不應輸出");
            }

            Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract")));
            Assert.False(File.Exists(Path.Combine(root, "outside.txt")));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void OpenReadRejectsMemberLimit()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string archivePath = Path.Combine(root, "many.zip");
            CreateArchive(archivePath, ("one.txt", "1"), ("two.txt", "2"));

            Assert.Throws<SafeArchiveException>(() => SafeZipArchive.OpenRead(archivePath, maxMembers: 1));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void ReadMetadataBytesHonorsSizeLimit()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string archivePath = Path.Combine(root, "metadata.zip");
            CreateArchive(archivePath, ("metadata.json", "{}"));
            using var archive = SafeZipArchive.OpenRead(archivePath);

            Assert.Equal("{}", System.Text.Encoding.UTF8.GetString(SafeZipArchive.ReadMetadataBytes(archive, "metadata.json", 2)!));
            Assert.Null(SafeZipArchive.ReadMetadataBytes(archive, "metadata.json", 1));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void WriteArchivePublishesBoundedOutputAtomically()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string archivePath = Path.Combine(root, "managed.zip");
            string sourcePath = Path.Combine(root, "source.txt");
            File.WriteAllText(sourcePath, "來源");

            SafeZipArchive.WriteArchive(
                archivePath,
                writer =>
                {
                    writer.WriteBytes("metadata.json", "{}"u8);
                    writer.WriteFile("source.txt", sourcePath);
                });

            using var archive = SafeZipArchive.OpenRead(archivePath);
            Assert.Equal("{}", ReadEntry(archive, "metadata.json"));
            Assert.Equal("來源", ReadEntry(archive, "source.txt"));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void WriteArchiveRejectsMemberLimit()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string archivePath = Path.Combine(root, "limited.zip");

            Assert.Throws<SafeArchiveException>(() => SafeZipArchive.WriteArchive(
                archivePath,
                writer =>
                {
                    writer.WriteBytes("one.txt", "1"u8);
                    writer.WriteBytes("two.txt", "2"u8);
                },
                maxMembers: 1));
            Assert.False(File.Exists(archivePath));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static void CreateArchive(string path, params (string Name, string Content)[] entries)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Create);
        foreach (var (name, content) in entries)
        {
            using var writer = new StreamWriter(archive.CreateEntry(name).Open());
            writer.Write(content);
        }
    }

    private static string ReadEntry(ZipArchive archive, string name)
    {
        using var reader = new StreamReader(archive.GetEntry(name)!.Open());
        return reader.ReadToEnd();
    }

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-zip-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
