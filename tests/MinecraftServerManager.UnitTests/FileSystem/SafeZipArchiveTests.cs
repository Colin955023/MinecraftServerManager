using System.IO.Compression;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.UnitTests.FileSystem;

public sealed class SafeZipArchiveTests
{
    [Fact]
    public void Extract_ValidArchive_PreservesFilesAndReportsProgress()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "sample.zip");
        string destination = Path.Combine(root, "extract");
        TestZip.Create(archivePath, ("nested/file.txt", "內容"));
        var progress = new List<(long Current, long Total)>();

        SafeZipArchive.Extract(archivePath, destination, (current, total) => progress.Add((current, total)), TestContext.Current.CancellationToken);

        Assert.Equal("內容", File.ReadAllText(Path.Combine(destination, "nested", "file.txt")));
        Assert.NotEmpty(progress);
        Assert.Equal(progress[^1].Total, progress[^1].Current);
    }

    [Fact]
    public void Extract_TraversalMember_Rejects()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "unsafe.zip");
        TestZip.Create(archivePath, ("../outside.txt", "不應輸出"));

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"), cancellationToken: TestContext.Current.CancellationToken));
        Assert.False(File.Exists(Path.Combine(root, "outside.txt")));
    }

    [Fact]
    public void OpenRead_ExceedsMemberLimit_Rejects()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "many.zip");
        TestZip.Create(archivePath, ("one.txt", "1"), ("two.txt", "2"));

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.OpenRead(archivePath, maxMembers: 1));
    }

    [Fact]
    public void WriteArchive_ValidEntries_PublishesAtomically()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "managed.zip");
        string sourcePath = Path.Combine(root, "source.txt");
        string metadataPath = Path.Combine(root, "metadata.json");
        File.WriteAllText(sourcePath, "來源");
        File.WriteAllText(metadataPath, "{}");

        SafeZipArchive.WriteArchive(
            archivePath,
            writer =>
            {
                writer.WriteFile("metadata.json", metadataPath);
                writer.WriteFile("source.txt", sourcePath);
            });

        using var archive = SafeZipArchive.OpenRead(archivePath);
        Assert.Equal("{}", ReadEntry(archive, "metadata.json"));
        Assert.Equal("來源", ReadEntry(archive, "source.txt"));
    }

    [Fact]
    public void WriteArchive_ExceedsMemberLimit_Rejects()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "limited.zip");
        string sourcePath = Path.Combine(root, "source.txt");
        File.WriteAllText(sourcePath, "1");

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.WriteArchive(
            archivePath,
            writer =>
            {
                writer.WriteFile("one.txt", sourcePath);
                writer.WriteFile("two.txt", sourcePath);
            },
            maxMembers: 1));
        Assert.False(File.Exists(archivePath));
    }

    [Fact]
    public void WriteArchive_HighlyCompressibleMember_CanBeExtracted()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "backup.zip");
        string sourcePath = Path.Combine(root, "r.0.0.mca");
        // 全零檔是壓縮比最高的情形，自己產生的備份仍須可還原
        File.WriteAllBytes(sourcePath, new byte[4 * 1024 * 1024]);

        SafeZipArchive.WriteArchive(archivePath, writer => writer.WriteFile("world/region/r.0.0.mca", sourcePath));
        SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"), cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(4 * 1024 * 1024, new FileInfo(Path.Combine(root, "extract", "world", "region", "r.0.0.mca")).Length);
    }

    [Fact]
    public void Extract_SmallHighRatioMember_Accepts()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "external.zip");
        // 其他工具以最佳壓縮打包的 8 KB 全零 region 檔，壓縮比超過 300
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            using var stream = archive.CreateEntry("world/poi/r.0.0.mca", CompressionLevel.Optimal).Open();
            stream.Write(new byte[8192]);
        }

        SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"), cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(8192, new FileInfo(Path.Combine(root, "extract", "world", "poi", "r.0.0.mca")).Length);
    }

    [Fact]
    public void OpenRead_LargeHighRatioMember_Rejects()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "bomb.zip");
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            using var stream = archive.CreateEntry("bomb.bin", CompressionLevel.Optimal).Open();
            byte[] zeros = new byte[1024 * 1024];
            for (int i = 0; i < 65; i++)
            {
                stream.Write(zeros);
            }
        }

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.OpenRead(archivePath));
    }

    [Fact]
    public void Extract_Cancelled_Throws()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "sample.zip");
        TestZip.Create(archivePath, ("file.txt", "內容"));
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        Assert.Throws<OperationCanceledException>(() =>
            SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"), cancellationToken: cts.Token));
    }

    [Fact]
    public void ReadEntryTextBounded_Utf8Content_HonorsByteLimit()
    {
        using var temp = new TempDirectory("msm-zip-bounded-");
        string archivePath = temp.Combine("a.zip");
        TestZip.Create(archivePath, ("a.txt", "內容"), ("empty.txt", ""));
        using var archive = ZipFile.OpenRead(archivePath);

        // 「內容」UTF-8 為 6 位元組：上限以位元組而非字元計算
        Assert.Equal("內容", SafeZipArchive.ReadEntryTextBounded(archive.GetEntry("a.txt")!, 6));
        Assert.Null(SafeZipArchive.ReadEntryTextBounded(archive.GetEntry("a.txt")!, 5));
        Assert.Equal(string.Empty, SafeZipArchive.ReadEntryTextBounded(archive.GetEntry("empty.txt")!, 0));
    }

    [Fact]
    public void ReadEntryBytesBounded_OverLimit_ReturnsNull()
    {
        using var temp = new TempDirectory("msm-zip-bounded-");
        string archivePath = temp.Combine("a.zip");
        TestZip.Create(archivePath, ("a.txt", "0123456789"));
        using var archive = ZipFile.OpenRead(archivePath);
        var entry = archive.GetEntry("a.txt")!;

        Assert.Null(SafeZipArchive.ReadEntryBytesBounded(entry, 9));
        Assert.Equal(10, SafeZipArchive.ReadEntryBytesBounded(entry, 10)!.Length);
    }

    [Fact]
    public void Extract_BackslashDirectoryEntry_RecognizesAsDirectory()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string archivePath = rootTemp.Combine("backslash-dir.zip");
        string destination = rootTemp.Combine("extract");

        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            archive.CreateEntry(@"dir\");
            using var writer = new StreamWriter(archive.CreateEntry(@"dir\nested.txt").Open());
            writer.Write("OK");
        }

        SafeZipArchive.Extract(archivePath, destination, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(Directory.Exists(Path.Combine(destination, "dir")));
        Assert.Equal("OK", File.ReadAllText(Path.Combine(destination, "dir", "nested.txt")));
    }

    [Fact]
    public void OpenRead_UnixSymlinkExternalAttributes_Rejects()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string archivePath = rootTemp.Combine("symlink.zip");

        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            var entry = archive.CreateEntry("link.txt");
            entry.ExternalAttributes = 0xA000 << 16;
            using var writer = new StreamWriter(entry.Open());
            writer.Write("target");
        }

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.OpenRead(archivePath));
    }

    private static string ReadEntry(ZipArchive archive, string name)
    {
        using var reader = new StreamReader(archive.GetEntry(name)!.Open());
        return reader.ReadToEnd();
    }
}
