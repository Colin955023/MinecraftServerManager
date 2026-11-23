using System.Security.Cryptography;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Services;

namespace MinecraftServerManager.UnitTests.Services;

public sealed class AppUpdateServiceTests : IDisposable
{
    private const string TrustedAssetBase = Core.AppInfo.RepositoryUrl + "/releases/download/v2.0.1/";

    private readonly TempDirectory _testDirTemp = new("msm_update_test_");
    private readonly string _testDir;

    public AppUpdateServiceTests()
    {
        _testDir = _testDirTemp.FullName;
    }

    public void Dispose() => _testDirTemp.Dispose();

    /// <summary>建立模擬發布檔下載的 HTTP 替身</summary>
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

        var update = TestUpdateResults.Create(downloadUrl: null, sha256ChecksumUrl: null);

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumMatchesAndPeHeaderValid_Succeeds()
    {
        byte[] validPe = CreateValidPeBytes();
        string expectedSha256 = Convert.ToHexStringLower(SHA256.HashData(validPe));

        var fakeHttp = CreateHttpPort($"{expectedSha256}  MinecraftServerManager-2.0.1.exe\n", validPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = TestUpdateResults.Create(
            downloadUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe",
            sha256ChecksumUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe.sha256");

        string resultPath = await service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(File.Exists(resultPath));
        Assert.True(fakeHttp.DownloadCount > 0);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData(TrustedAssetBase + "update.exe.sha256", "not-a-hash")]
    [InlineData("https://example.com/update.exe.sha256", null)]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumIsMissingOrInvalid_RejectsDownload(
        string? checksumUrl,
        string? checksumResponse)
    {
        var fakeHttp = CreateHttpPort(checksumResponse, CreateValidPeBytes());
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());
        var update = TestUpdateResults.Create(
            downloadUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe",
            sha256ChecksumUrl: checksumUrl);

        await Assert.ThrowsAsync<InvalidDataException>(() => service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken));

        Assert.Equal(0, fakeHttp.DownloadCount);
        Assert.False(File.Exists(Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe")));
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumRequestFails_RejectsDownload()
    {
        var fakeHttp = CreateHttpPort(null, CreateValidPeBytes(), new IOException("checksum unavailable"));
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());
        var update = TestUpdateResults.Create(
            downloadUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe",
            sha256ChecksumUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe.sha256");

        await Assert.ThrowsAsync<IOException>(() => service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken));

        Assert.Equal(0, fakeHttp.DownloadCount);
    }

    [Fact]
    public async Task DownloadAndVerifyUpdateAsync_WhenChecksumMismatch_DeletesFileAndThrows()
    {
        byte[] validPe = CreateValidPeBytes();
        string fakeSha256 = new('a', 64);

        var fakeHttp = CreateHttpPort(fakeSha256, validPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = TestUpdateResults.Create(
            downloadUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe",
            sha256ChecksumUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe.sha256");

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken));

        string targetFile = Path.Combine(_testDir, "MinecraftServerManager-2.0.1.exe");
        Assert.False(File.Exists(targetFile));
    }

    [Theory]
    [InlineData("not_pe")]
    [InlineData("dos_only")]
    public async Task DownloadAndVerifyUpdateAsync_WhenPeHeaderInvalid_DeletesFileAndThrows(string kind)
    {
        byte[] invalidPe = kind switch
        {
            "dos_only" => [0x4D, 0x5A, .. new byte[254]],
            _ => new byte[128],
        };
        string sha256 = Convert.ToHexStringLower(SHA256.HashData(invalidPe));

        var fakeHttp = CreateHttpPort(sha256, invalidPe);

        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        var update = TestUpdateResults.Create(
            downloadUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe",
            sha256ChecksumUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe.sha256");

        await Assert.ThrowsAsync<InvalidDataException>(() =>
            service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken));

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

        var update = TestUpdateResults.Create(
            downloadUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe",
            sha256ChecksumUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe.sha256");

        string resultPath = await service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(targetFile, resultPath);
        Assert.Equal(0, fakeHttp.DownloadCount);
    }

    [Theory]
    [InlineData("https://example.com/MinecraftServerManager-2.0.1.exe")]
    [InlineData("https://github.com/Other/Repo/releases/download/v2.0.1/MinecraftServerManager-2.0.1.exe")]
    [InlineData("https://github.com:8443/Colin955023/MinecraftServerManager/releases/download/v2.0.1/MinecraftServerManager-2.0.1.exe")]
    [InlineData("https://user:pass@github.com/Colin955023/MinecraftServerManager/releases/download/v2.0.1/MinecraftServerManager-2.0.1.exe")]
    public async Task DownloadAndVerifyUpdateAsync_WhenDownloadUrlNotOfficialRelease_RejectsDownload(string downloadUrl)
    {
        var fakeHttp = CreateHttpPort(new string('a', 64), CreateValidPeBytes());
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());
        var update = TestUpdateResults.Create(
            downloadUrl: downloadUrl,
            sha256ChecksumUrl: TrustedAssetBase + "MinecraftServerManager-2.0.1.exe.sha256");

        await Assert.ThrowsAsync<InvalidDataException>(() => service.DownloadAndVerifyUpdateAsync(update, cancellationToken: TestContext.Current.CancellationToken));

        Assert.Equal(0, fakeHttp.DownloadCount);
    }

    [Fact]
    public void ApplyUpdateAndRestart_WhenFileDoesNotExist_ThrowsFileNotFoundException()
    {
        var fakeHttp = CreateHttpPort(null, null);
        var service = new AppUpdateService(fakeHttp, _testDir, NoOp.Create<IProcessRunner>());

        Assert.Throws<FileNotFoundException>(() =>
            service.ApplyUpdateAndRestart(Path.Combine(_testDir, "non_existent.exe"), static launch => launch()));
    }
}
