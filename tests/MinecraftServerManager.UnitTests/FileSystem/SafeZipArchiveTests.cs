using System.IO.Compression;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.UnitTests.FileSystem;

public sealed class SafeZipArchiveTests
{
    [Fact]
    public void ExtractPreservesFilesAndReportsProgress()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "sample.zip");
        string destination = Path.Combine(root, "extract");
        CreateArchive(archivePath, ("nested/file.txt", "內容"));
        var progress = new List<(long Current, long Total)>();

        SafeZipArchive.Extract(archivePath, destination, (current, total) => progress.Add((current, total)));

        Assert.Equal("內容", File.ReadAllText(Path.Combine(destination, "nested", "file.txt")));
        Assert.NotEmpty(progress);
        Assert.Equal(progress[^1].Total, progress[^1].Current);
    }

    [Fact]
    public void ExtractRejectsTraversalMember()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "unsafe.zip");
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            using var writer = new StreamWriter(archive.CreateEntry("../outside.txt").Open());
            writer.Write("不應輸出");
        }

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract")));
        Assert.False(File.Exists(Path.Combine(root, "outside.txt")));
    }

    [Fact]
    public void OpenReadRejectsMemberLimit()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "many.zip");
        CreateArchive(archivePath, ("one.txt", "1"), ("two.txt", "2"));

        Assert.Throws<SafeArchiveException>(() => SafeZipArchive.OpenRead(archivePath, maxMembers: 1));
    }

    [Fact]
    public void WriteArchivePublishesBoundedOutputAtomically()
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
    public void WriteArchiveRejectsMemberLimit()
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
    public void WrittenArchiveWithHighlyCompressibleMemberCanBeExtracted()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "backup.zip");
        string sourcePath = Path.Combine(root, "r.0.0.mca");
        // 全零檔是壓縮比最高的情形，自己產生的備份仍須可還原
        File.WriteAllBytes(sourcePath, new byte[4 * 1024 * 1024]);

        SafeZipArchive.WriteArchive(archivePath, writer => writer.WriteFile("world/region/r.0.0.mca", sourcePath));
        SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"));

        Assert.Equal(4 * 1024 * 1024, new FileInfo(Path.Combine(root, "extract", "world", "region", "r.0.0.mca")).Length);
    }

    [Fact]
    public void ExtractAcceptsSmallHighlyCompressibleMemberFromOtherTools()
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

        SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"));

        Assert.Equal(8192, new FileInfo(Path.Combine(root, "extract", "world", "poi", "r.0.0.mca")).Length);
    }

    [Fact]
    public void OpenReadRejectsLargeMemberWithExcessiveCompressionRatio()
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
    public void ExtractHonorsCancellationToken()
    {
        using var rootTemp = new TempDirectory("msm-zip-");
        string root = rootTemp.FullName;
        string archivePath = Path.Combine(root, "sample.zip");
        CreateArchive(archivePath, ("file.txt", "內容"));
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        Assert.Throws<OperationCanceledException>(() =>
            SafeZipArchive.Extract(archivePath, Path.Combine(root, "extract"), cancellationToken: cts.Token));
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
}
