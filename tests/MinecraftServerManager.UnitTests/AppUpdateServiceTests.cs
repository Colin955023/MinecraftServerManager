using System.Security.Cryptography;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Services;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class AppUpdateServiceTests : IDisposable
{
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
        catch
        {
        }
    }

    private sealed class FakeDownloadHttpPort : IHttpPort
    {
        public string? ChecksumResponse { get; set; }
        public Exception? ChecksumException { get; set; }
        public byte[]? FileBytesToDownload { get; set; }
        public bool DownloadInvoked { get; private set; }

        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default)
        {
            if (ChecksumException is not null)
            {
                return Task.FromException<string?>(ChecksumException);
            }

            return Task.FromResult(ChecksumResponse);
        }

        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default)
        {
            DownloadInvoked = true;
            if (FileBytesToDownload is null)
            {
                return Task.FromResult(new HttpResult(false, "Download failed"));
            }

            Directory.CreateDirectory(Path.GetDirectoryName(targetPath)!);
            File.WriteAllBytes(targetPath, FileBytesToDownload);

            if (!string.IsNullOrEmpty(expectedHash))
            {
                string actualHash = Convert.ToHexStringLower(SHA256.HashData(FileBytesToDownload));
                if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                {
                    return Task.FromResult(new HttpResult(false, "Hash mismatch"));
                }
            }

            progress?.Report(new HttpProgress(FileBytesToDownload.Length, FileBytesToDownload.Length));
            return Task.FromResult(new HttpResult(true, null, FileBytesToDownload.Length));
        }

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<string?> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();
    }

    private static byte[] CreateValidPeBytes(int length = 256)
    {
        byte[] bytes = new byte[Math.Max(length, 64)];
        bytes[0] = 0x4D; // 'M'
        bytes[1] = 0x5A; // 'Z'
        return bytes;
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenDownloadUrlEmpty_ThrowsInvalidOperationException()
    {
        var fakeHttp = new FakeDownloadHttpPort();
        var service = new AppUpdateService(fakeHttp, _testDir);

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
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

        var fakeHttp = new FakeDownloadHttpPort
        {
            ChecksumResponse = $"{expectedSha256}  MinecraftServerManager-2.0.1.exe\n",
            FileBytesToDownload = validPe,
        };

        var service = new AppUpdateService(fakeHttp, _testDir);

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        string resultPath = await service.DownloadAndVerifyUpdateAsync(update);

        Assert.True(File.Exists(resultPath));
        Assert.True(fakeHttp.DownloadInvoked);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData("https://example.com/update.exe.sha256", "not-a-hash")]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumIsMissingOrInvalid_RejectsDownload(
        string? checksumUrl,
        string? checksumResponse)
    {
        var fakeHttp = new FakeDownloadHttpPort
        {
            ChecksumResponse = checksumResponse,
            FileBytesToDownload = CreateValidPeBytes(),
        };
        var service = new AppUpdateService(fakeHttp, _testDir);
        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: checksumUrl,
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<InvalidDataException>(() => service.DownloadAndVerifyUpdateAsync(update));

        Assert.False(fakeHttp.DownloadInvoked);
        Assert.False(File.Exists(Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe")));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumRequestFails_RejectsDownload()
    {
        var fakeHttp = new FakeDownloadHttpPort
        {
            ChecksumException = new IOException("checksum unavailable"),
            FileBytesToDownload = CreateValidPeBytes(),
        };
        var service = new AppUpdateService(fakeHttp, _testDir);
        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        await Assert.ThrowsAsync<IOException>(() => service.DownloadAndVerifyUpdateAsync(update));

        Assert.False(fakeHttp.DownloadInvoked);
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumMismatch_DeletesFileAndThrows()
    {
        byte[] validPe = CreateValidPeBytes();
        string fakeSha256 = new('a', 64);

        var fakeHttp = new FakeDownloadHttpPort
        {
            ChecksumResponse = fakeSha256,
            FileBytesToDownload = validPe,
        };

        var service = new AppUpdateService(fakeHttp, _testDir);

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
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

        var fakeHttp = new FakeDownloadHttpPort
        {
            ChecksumResponse = sha256,
            FileBytesToDownload = invalidPe,
        };

        var service = new AppUpdateService(fakeHttp, _testDir);

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
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

        var fakeHttp = new FakeDownloadHttpPort
        {
            ChecksumResponse = expectedSha256,
            FileBytesToDownload = validPe,
        };

        var service = new AppUpdateService(fakeHttp, _testDir);

        var update = new UpdateCheckResult(
            HasUpdate: true,
            CurrentVersion: "2.0.0",
            LatestVersion: "2.0.1",
            ReleaseTitle: "2.0.1",
            ReleaseNotes: "測試",
            DownloadUrl: "https://example.com/MinecraftServerManager-2.0.1.exe",
            Sha256ChecksumUrl: "https://example.com/MinecraftServerManager-2.0.1.exe.sha256",
            ReleasePageUrl: "https://example.com");

        string resultPath = await service.DownloadAndVerifyUpdateAsync(update);

        Assert.Equal(targetFile, resultPath);
        Assert.False(fakeHttp.DownloadInvoked);
    }

    [Fact]
    public void ApplyUpdateAndRestart_WhenFileDoesNotExist_ThrowsFileNotFoundException()
    {
        var fakeHttp = new FakeDownloadHttpPort();
        var service = new AppUpdateService(fakeHttp, _testDir);

        Assert.Throws<FileNotFoundException>(() =>
            service.ApplyUpdateAndRestart(Path.Combine(_testDir, "non_existent.exe")));
    }
}
