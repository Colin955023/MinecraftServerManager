using System.Security.Cryptography;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Services;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed partial class AppUpdateServiceTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AppUpdateServiceTests));
    private readonly string _testDir;

    public AppUpdateServiceTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_update_test_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testDir))
            {
                Directory.Delete(_testDir, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    /// <summary>建立模擬發布檔下載的 HTTP 替身：校驗檔以文字回應、檔案內容寫入目標並比對雜湊</summary>
    private static StubHttpPort CreateHttpPort(string? checksumResponse, byte[]? fileBytes, Exception? checksumException = null) =>
        new()
        {
            TextHandler = _ => checksumException is null ? checksumResponse : throw checksumException,
            DownloadHandler = request =>
            {
                if (fileBytes is null)
                {
                    return Task.FromResult(new HttpResult(false, "Download failed"));
                }

                Directory.CreateDirectory(Path.GetDirectoryName(request.TargetPath)!);
                File.WriteAllBytes(request.TargetPath, fileBytes);

                if (!string.IsNullOrEmpty(request.ExpectedHash))
                {
                    string actualHash = Convert.ToHexStringLower(SHA256.HashData(fileBytes));
                    if (!string.Equals(actualHash, request.ExpectedHash, StringComparison.OrdinalIgnoreCase))
                    {
                        return Task.FromResult(new HttpResult(false, "Hash mismatch"));
                    }
                }

                request.Progress?.Report(new HttpProgress(fileBytes.Length, fileBytes.Length));
                return Task.FromResult(new HttpResult(true, null, fileBytes.Length));
            },
        };

    private static byte[] CreateValidPeBytes(int length = 256)
    {
        // 最小合法 PE32+：DOS 標頭 + PE 簽章 + COFF 標頭 + 選用標頭（供 PEReader 解析）
        byte[] bytes = new byte[Math.Max(length, 512)];
        bytes[0] = 0x4D; // 'M'
        bytes[1] = 0x5A; // 'Z'
        bytes[0x3C] = 0x40; // e_lfanew
        bytes[0x40] = 0x50; // 'P'
        bytes[0x41] = 0x45; // 'E'
        bytes[0x44] = 0x64; // Machine = AMD64 (0x8664)
        bytes[0x45] = 0x86;
        bytes[0x54] = 0xF0; // SizeOfOptionalHeader = 240
        bytes[0x58] = 0x0B; // Magic = PE32+ (0x20B)
        bytes[0x59] = 0x02;
        return bytes;
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenDownloadUrlEmpty_ThrowsInvalidOperationException()
    {
        var fakeHttp = CreateHttpPort(null, null);
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: null,
            Sha256ChecksumUrl: null,
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            service.DownloadAndVerifyUpdateAsync(update));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumMatchesAndPeHeaderValid_Succeeds()
    {
        byte[] validPe = CreateValidPeBytes();
        string expectedSha256 = Convert.ToHexStringLower(SHA256.HashData(validPe));

        var fakeHttp = CreateHttpPort($"{expectedSha256}  MinecraftServerManager-2.0.1.exe\n", validPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        string resultPath = await service.DownloadAndVerifyUpdateAsync(update);

        Assert.True(File.Exists(resultPath));
        Assert.True(fakeHttp.DownloadCount > 0);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData("https://example.com/update.exe.sha256", "not-a-hash")]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumIsMissingOrInvalid_RejectsDownload(
        string? checksumUrl,
        string? checksumResponse)
    {
        var fakeHttp = CreateHttpPort(checksumResponse, CreateValidPeBytes());
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());
        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: checksumUrl,
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<InvalidDataException>(() => service.DownloadAndVerifyUpdateAsync(update));

        Assert.Equal(0, fakeHttp.DownloadCount);
        Assert.False(File.Exists(Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe")));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumRequestFails_RejectsDownload()
    {
        var fakeHttp = CreateHttpPort(null, CreateValidPeBytes(), new IOException("checksum unavailable"));
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());
        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<IOException>(() => service.DownloadAndVerifyUpdateAsync(update));

        Assert.Equal(0, fakeHttp.DownloadCount);
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumMismatch_DeletesFileAndThrows()
    {
        byte[] validPe = CreateValidPeBytes();
        string fakeSha256 = new('a', 64);

        var fakeHttp = CreateHttpPort(fakeSha256, validPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAnyAsync<Exception>(() =>
            service.DownloadAndVerifyUpdateAsync(update));

        string targetFile = Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe");
        Assert.False(File.Exists(targetFile));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenPeHeaderInvalid_DeletesFileAndThrows()
    {
        byte[] invalidPe = new byte[128];
        invalidPe[0] = 0x00;
        invalidPe[1] = 0x00;
        string sha256 = Convert.ToHexStringLower(SHA256.HashData(invalidPe));

        var fakeHttp = CreateHttpPort(sha256, invalidPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<InvalidDataException>(() =>
            service.DownloadAndVerifyUpdateAsync(update));

        string targetFile = Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe");
        Assert.False(File.Exists(targetFile));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenCachedFileMatches_ReusesWithoutDownloading()
    {
        byte[] validPe = CreateValidPeBytes();
        string expectedSha256 = Convert.ToHexStringLower(SHA256.HashData(validPe));

        string targetFile = Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe");
        File.WriteAllBytes(targetFile, validPe);

        var fakeHttp = CreateHttpPort(expectedSha256, validPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        string resultPath = await service.DownloadAndVerifyUpdateAsync(update);

        Assert.Equal(targetFile, resultPath);
        Assert.Equal(0, fakeHttp.DownloadCount);
    }

    [Fact]
    public void ApplyUpdateAndRestart_WhenFileDoesNotExist_ThrowsFileNotFoundException()
    {
        var fakeHttp = CreateHttpPort(null, null);
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        Assert.Throws<FileNotFoundException>(() =>
            service.ApplyUpdateAndRestart(Path.Combine(_testDir, "non_existent.exe")));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenOnlyDosHeaderPresent_RejectsFile()
    {
        byte[] dosOnly = new byte[256];
        dosOnly[0] = 0x4D;
        dosOnly[1] = 0x5A;
        string sha256 = Convert.ToHexStringLower(SHA256.HashData(dosOnly));
        var fakeHttp = CreateHttpPort(sha256, dosOnly);
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());
        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: Core.AppInfo.Version,
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<InvalidDataException>(() => service.DownloadAndVerifyUpdateAsync(update));

        Assert.False(File.Exists(Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe")));
    }
}
