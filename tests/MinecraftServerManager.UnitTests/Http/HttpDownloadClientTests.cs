using System.Net;
using System.Security.Cryptography;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Http;

namespace MinecraftServerManager.UnitTests.Http;

public sealed class HttpDownloadClientTests
{
    [Fact]
    public async Task DownloadAsync_Success_WritesAtomicallyAndReportsProgress()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("下載內容"u8.ToArray()),
        });
        string target = fixture.TargetPath;
        var progress = new List<HttpProgress>();

        var result = await fixture.Client.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxBytes = 1024 },
            new SynchronousProgress<HttpProgress>(progress.Add),
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("下載內容", File.ReadAllText(target));
        Assert.NotEmpty(progress);
        Assert.Equal(result.BytesProcessed, progress[^1].BytesDownloaded);
    }

    [Theory]
    [InlineData("oversized")]
    [InlineData("hash_mismatch")]
    public async Task DownloadAsync_ValidationFailure_KeepsExistingTarget(string failureKind)
    {
        byte[] payload = failureKind == "oversized" ? "太大的內容"u8.ToArray() : "遭竄改內容"u8.ToArray();
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(payload),
        });
        string target = fixture.TargetPath;
        await File.WriteAllTextAsync(target, "保留內容", TestContext.Current.CancellationToken);

        var options = new HttpDownloadOptions
        {
            MaxBytes = failureKind == "oversized" ? 1 : 1024,
            MaxAttempts = 1,
        };
        string? expectedHash = failureKind == "hash_mismatch" ? new string('a', 64) : null;

        var result = await fixture.Client.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            options,
            expectedHash: expectedHash,
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Success);
        if (failureKind == "hash_mismatch")
        {
            Assert.Contains("雜湊", result.Error);
        }
        Assert.Equal("保留內容", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task DownloadAsync_CompressedContent_Succeeds()
    {
        var content = new ByteArrayContent("解壓縮後的內容"u8.ToArray());
        content.Headers.ContentEncoding.Add("gzip");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = content,
        });
        string target = fixture.TargetPath;

        var result = await fixture.Client.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxBytes = 1024 },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("解壓縮後的內容", File.ReadAllText(target));
    }

    [Fact]
    public async Task DownloadAsync_TransientStatus_Retries()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.ServiceUnavailable),
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent("完成"u8.ToArray()) });
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxAttempts = 2, RetryDelay = TimeSpan.Zero },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal(2, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadAsync_UnsafeRedirect_Rejects()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        var redirect = new HttpResponseMessage(HttpStatusCode.Found);
        redirect.Headers.Location = new Uri("http://example.com/file");
        using var fixture = new DownloadFixture(redirect);
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Success);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task HttpPortDownloadAsync_Success_BridgesResult()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("port_download.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("介面下載"u8.ToArray()),
        });
        IHttpPort http = fixture.Client;
        var progressReports = new List<HttpProgress>();

        var result = await http.DownloadAsync(
            new Uri("https://example.com/port-file"),
            target,
            new SynchronousProgress<HttpProgress>(progressReports.Add),
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("介面下載", File.ReadAllText(target));
        Assert.NotEmpty(progressReports);
        Assert.Equal(result.BytesProcessed, progressReports[^1].BytesDownloaded);
    }

    [Fact]
    public async Task DownloadAsync_IPv6Loopback_ThrowsBeforeRequest()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("file.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK));
        var (handler, http) = fixture;

        var exception = await Assert.ThrowsAsync<HttpSecurityException>(() =>
            http.DownloadAsync(new Uri("https://[::1]/download"), target, cancellationToken: TestContext.Current.CancellationToken));

        Assert.Contains("非公開", exception.Message);
        Assert.Equal(0, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadAsync_ConnectRejectedBySecurityPolicy_FailsWithoutRetry()
    {
        using var temp = new TempDirectory("msm-http-");
        var handler = new QueueHandler
        {
            SendException = new HttpRequestException("連線失敗", new HttpSecurityException("目標解析為非公開位址")),
        };
        using var client = new HttpClient(handler);
        var downloader = new HttpDownloadClient(client, TimeProvider.System);

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            temp.Combine("download.bin"),
            new HttpDownloadOptions { MaxAttempts = 3, RetryDelay = TimeSpan.Zero },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Success);
        Assert.Equal("目標解析為非公開位址", result.Error);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadAsync_PartialFileWith206_Resumes()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "Part1", TestContext.Current.CancellationToken);

        var response = new HttpResponseMessage(HttpStatusCode.PartialContent)
        {
            Content = new ByteArrayContent("Part2"u8.ToArray()),
        };
        response.Content.Headers.ContentRange = new System.Net.Http.Headers.ContentRangeHeaderValue(5, 9, 10);

        using var fixture = new DownloadFixture(response);
        var (handler, downloader) = fixture;

        // 跨呼叫續傳須有預期雜湊可驗證最終結果
        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            expectedHash: Convert.ToHexStringLower(SHA256.HashData("Part1Part2"u8)),
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("Part1Part2", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
        Assert.NotNull(handler.LastRequest?.Headers.Range);
        Assert.Equal(5, handler.LastRequest!.Headers.Range!.Ranges.First().From);
    }

    [Fact]
    public async Task DownloadAsync_RangeAnsweredWith200_DownloadsFull()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "OldCorruptContent", TestContext.Current.CancellationToken);

        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("FreshFullContent"u8.ToArray()),
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(new Uri("https://example.com/file"), target, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("FreshFullContent", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task DownloadAsync_RangeAnsweredWith416_ResetsPartialFile()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "StaleBytes", TestContext.Current.CancellationToken);

        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.RequestedRangeNotSatisfiable),
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent("FreshData"u8.ToArray()) });
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxAttempts = 2, RetryDelay = TimeSpan.Zero },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("FreshData", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
        Assert.Equal(2, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadAsync_StalePartialWithoutHash_DiscardsPartial()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        await File.WriteAllTextAsync(target + ".part", "StaleBytes", TestContext.Current.CancellationToken);

        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("FreshContent"u8.ToArray()),
        });
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(new Uri("https://example.com/file"), target, cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("FreshContent", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
        Assert.Null(handler.LastRequest?.Headers.Range);
    }

    [Fact]
    public async Task DownloadAsync_ETagChanged_DiscardsPartial()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "OldVersionPart", TestContext.Current.CancellationToken);

        var initialResponse = new HttpResponseMessage(HttpStatusCode.PartialContent)
        {
            Content = new ByteArrayContent("MoreOldVersion"u8.ToArray()),
        };
        initialResponse.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"v2\"");

        var fallbackResponse = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("BrandNewVersionContent"u8.ToArray()),
        };
        fallbackResponse.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"v2\"");

        // 第一次用 429 記住 v1
        var rateLimited = new HttpResponseMessage(HttpStatusCode.TooManyRequests);
        rateLimited.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"v1\"");

        using var fixture = new DownloadFixture(rateLimited, initialResponse, fallbackResponse);
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxAttempts = 3, RetryDelay = TimeSpan.Zero },
            expectedHash: Convert.ToHexStringLower(SHA256.HashData("BrandNewVersionContent"u8)),
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("BrandNewVersionContent", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task DownloadAsync_ResumeAfterRetry_SendsIfRangeOnlyForStrongETag(bool isWeak)
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        await File.WriteAllTextAsync(target + ".part", "Hello", TestContext.Current.CancellationToken);

        var rateLimited = new HttpResponseMessage(HttpStatusCode.TooManyRequests);
        rateLimited.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"v1\"", isWeak);
        var partial = new HttpResponseMessage(HttpStatusCode.PartialContent)
        {
            Content = new ByteArrayContent("World"u8.ToArray()),
        };
        partial.Content.Headers.ContentRange = new System.Net.Http.Headers.ContentRangeHeaderValue(5, 9, 10);
        using var fixture = new DownloadFixture(rateLimited, partial);
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxAttempts = 2, RetryDelay = TimeSpan.Zero },
            expectedHash: Convert.ToHexStringLower(SHA256.HashData("HelloWorld"u8)),
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal("HelloWorld", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
        Assert.Equal(5, handler.LastRequest?.Headers.Range?.Ranges.Single().From);
        Assert.Equal(isWeak ? null : "\"v1\"", handler.LastRequest?.Headers.IfRange?.EntityTag?.Tag);
    }

    [Fact]
    public async Task DownloadAsync_BodyStallsBeyondIdleTimeout_FailsWithTimeout()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StreamContent(new PacedStream(chunks: 1, delay: TimeSpan.Zero, stallAfterLastChunk: true)),
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { Timeout = TimeSpan.FromMilliseconds(300), MaxAttempts = 1 },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Success);
        Assert.Equal("HTTP 請求逾時", result.Error);
        Assert.False(File.Exists(target));
    }

    [Fact]
    public async Task DownloadAsync_SlowButSteadyBody_Succeeds()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            // 單段延遲 100 ms 遠小於逾時 600 ms（約 6 倍裕度）；總時長 700 ms 超過逾時，確認判定為閒置而非總時長
            Content = new StreamContent(new PacedStream(chunks: 8, delay: TimeSpan.FromMilliseconds(100), stallAfterLastChunk: false)),
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { Timeout = TimeSpan.FromMilliseconds(600), MaxAttempts = 1 },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal(8, new FileInfo(target).Length);
    }

    [Fact]
    public async Task DownloadAsync_CallerCancelled_ThrowsOperationCanceledException()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(TestContext.Current.CancellationToken);
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StreamContent(new CancelOnSecondReadStream(cts)),
        });
        var (_, downloader) = fixture;

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            downloader.DownloadAsync(
                new Uri("https://example.com/file"),
                target,
                new HttpDownloadOptions { MaxAttempts = 3 },
                cancellationToken: cts.Token));
        Assert.False(File.Exists(target));
    }

    [Fact]
    public async Task DownloadAsync_SafeHttpsRedirect_DownloadsTarget()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        var redirect = new HttpResponseMessage(HttpStatusCode.Found);
        redirect.Headers.Location = new Uri("https://cdn.example.com/actual.bin");
        using var fixture = new DownloadFixture(
            redirect,
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent("重導向成功"u8.ToArray()) });
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.Equal(2, handler.RequestCount);
        Assert.Equal("重導向成功", await File.ReadAllTextAsync(target, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task DownloadAsync_ChunkedStreamExceedsMaxBytesWithoutContentLength_AbortsAndFails()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new UnknownLengthContent("0123456789"u8.ToArray()),
        };
        Assert.Null(response.Content.Headers.ContentLength);

        using var fixture = new DownloadFixture(response);
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxBytes = 4, MaxAttempts = 1 },
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Success);
        Assert.Contains("大小上限", result.Error);
        Assert.False(File.Exists(target));
    }

    private sealed class UnknownLengthContent(byte[] data) : HttpContent
    {
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            stream.WriteAsync(data, 0, data.Length);

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context, CancellationToken cancellationToken) =>
            stream.WriteAsync(data.AsMemory(), cancellationToken).AsTask();

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }
    }

    private sealed class CancelOnSecondReadStream(CancellationTokenSource cts) : AsyncReadOnlyStream
    {
        private int _reads;

        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (_reads++ == 0)
            {
                buffer.Span[0] = (byte)'A';
                return ValueTask.FromResult(1);
            }

            cts.Cancel();
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(0);
        }
    }

    /// <summary>每次讀出一個位元組並於區塊間延遲；可於最後一塊後永久停滯</summary>
    private sealed class PacedStream(int chunks, TimeSpan delay, bool stallAfterLastChunk) : AsyncReadOnlyStream
    {
        private int _sent;

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (_sent >= chunks)
            {
                if (stallAfterLastChunk)
                {
                    await Task.Delay(Timeout.Infinite, cancellationToken);
                }

                return 0;
            }

            if (_sent > 0)
            {
                await Task.Delay(delay, cancellationToken);
            }

            buffer.Span[0] = 1;
            _sent++;
            return 1;
        }
    }
}
