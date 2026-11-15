using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Http;

namespace MinecraftServerManager.UnitTests.Http;

public sealed class HttpDownloadClientTests
{
    [Fact]
    public void UrlPolicyRejectsInsecureAndPrivateTargets()
    {
        Assert.Throws<HttpSecurityException>(static () => HttpUrlPolicy.ValidateStatic(new Uri("http://example.com/file")));
        Assert.Throws<HttpSecurityException>(static () => HttpUrlPolicy.ValidateStatic(new Uri("https://user:pass@example.com/file")));
        Assert.Throws<HttpSecurityException>(static () => HttpUrlPolicy.ValidateStatic(new Uri("https://127.0.0.1/file")));
    }

    [Fact]
    public async Task ConnectCallbackRejectsPrivateDnsResultBeforeConnecting()
    {
        int resolveCount = 0;

        var exception = await Assert.ThrowsAsync<HttpSecurityException>(async () =>
            await HttpUrlPolicy.ConnectAsync(
                new DnsEndPoint("rebind.example", 443),
                (_, _) =>
                {
                    resolveCount++;
                    return Task.FromResult(new[] { IPAddress.Loopback });
                },
                CancellationToken.None));

        Assert.Contains("非公開", exception.Message);
        Assert.Equal(1, resolveCount);
    }

    [Fact]
    public async Task DownloadStreamsToAtomicTargetAndReportsProgress()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("下載內容"u8.ToArray()),
        });
        var (_, downloader) = fixture;
        var progress = new List<HttpProgress>();

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxBytes = 1024 },
            new SynchronousProgress<HttpProgress>(progress.Add));

        Assert.True(result.Success);
        Assert.Equal("下載內容", File.ReadAllText(target));
        Assert.NotEmpty(progress);
        Assert.Equal(result.BytesProcessed, progress[^1].BytesDownloaded);
    }

    [Fact]
    public async Task DownloadRejectsOversizedResponseWithoutOverwritingTarget()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        File.WriteAllText(target, "保留內容");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("太大的內容"u8.ToArray()),
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxBytes = 1 });

        Assert.False(result.Success);
        Assert.Equal("保留內容", File.ReadAllText(target));
    }

    [Fact]
    public async Task DownloadAllowsCompressedResponseContentSafely()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        var content = new ByteArrayContent("解壓縮後的內容"u8.ToArray());
        content.Headers.ContentEncoding.Add("gzip");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = content,
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxBytes = 1024 });

        Assert.True(result.Success);
        Assert.Equal("解壓縮後的內容", File.ReadAllText(target));
    }

    [Fact]
    public async Task DownloadRetriesTransientStatus()
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
            new HttpDownloadOptions { MaxAttempts = 2, RetryDelay = TimeSpan.Zero });

        Assert.True(result.Success);
        Assert.Equal(2, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadRejectsUnsafeRedirect()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        var redirect = new HttpResponseMessage(HttpStatusCode.Found);
        redirect.Headers.Location = new Uri("http://example.com/file");
        using var fixture = new DownloadFixture(redirect);
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(new Uri("https://example.com/file"), target);

        Assert.False(result.Success);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task GetJsonDocumentAsyncDeserializesValidResponse()
    {
        string json = """{"name": "Minecraft", "version": 2}""";
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        });
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.True(response.IsSuccess);
        Assert.Equal(200, response.StatusCode);
        Assert.NotNull(response.Payload);
        using var doc = response.Payload;
        Assert.Equal("Minecraft", doc.RootElement.GetProperty("name").GetString());
        Assert.Equal(2, doc.RootElement.GetProperty("version").GetInt32());
        Assert.Empty(response.ErrorKind);
    }

    [Theory]
    [InlineData(HttpStatusCode.NotFound, "not_found")]
    [InlineData(HttpStatusCode.BadRequest, "invalid_request")]
    [InlineData(HttpStatusCode.InternalServerError, "transient")]
    public async Task GetJsonDocumentAsyncClassifiesStatusCodes(HttpStatusCode statusCode, string expectedErrorKind)
    {
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(statusCode),
            new HttpResponseMessage(statusCode),
            new HttpResponseMessage(statusCode));
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal((int)statusCode, response.StatusCode);
        Assert.Equal(expectedErrorKind, response.ErrorKind);
        Assert.Null(response.Payload);
    }

    [Fact]
    public async Task GetJsonDocumentAsyncRetriesRateLimitedThenFails()
    {
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.TooManyRequests),
            new HttpResponseMessage(HttpStatusCode.TooManyRequests),
            new HttpResponseMessage(HttpStatusCode.TooManyRequests));
        var (handler, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal(429, response.StatusCode);
        Assert.Equal("rate_limited", response.ErrorKind);
        Assert.Equal(3, handler.RequestCount);
    }

    [Fact]
    public async Task GetJsonDocumentAsyncRejectsInvalidJson()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("not a valid json", Encoding.UTF8, "application/json"),
        });
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal("invalid_response", response.ErrorKind);
    }

    [Fact]
    public async Task GetJsonDocumentAsyncAllowsCompressedResponseContentSafely()
    {
        var content = new StringContent("""{"name": "test", "version": 1}""", Encoding.UTF8, "application/json");
        content.Headers.ContentEncoding.Add("gzip");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = content,
        });
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.True(response.IsSuccess);
        Assert.NotNull(response.Payload);
        using var doc = response.Payload;
        Assert.Equal("test", doc.RootElement.GetProperty("name").GetString());
        Assert.Equal(1, doc.RootElement.GetProperty("version").GetInt32());
    }

    [Fact]
    public async Task GetTextAsyncReturnsContentAndEnforcesLimits()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("純文字內容", Encoding.UTF8, "text/plain"),
        });
        var (_, http) = fixture;

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"));

        Assert.Equal("純文字內容", text);
    }

    [Fact]
    public async Task GetTextAsyncReturnsNullOnOversizedContent()
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(new byte[100]),
        };
        response.Content.Headers.ContentLength = HttpDownloadClient.MaxTextBytes + 1;
        using var fixture = new DownloadFixture(response);
        var (_, http) = fixture;

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"));

        Assert.Null(text);
    }

    [Fact]
    public async Task RequestInjectsDefaultUserAgent()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        });
        var (handler, http) = fixture;

        await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.NotNull(handler.LastRequest);
        string userAgent = handler.LastRequest.Headers.UserAgent.ToString();
        Assert.Contains($"MinecraftServerManager/{Core.AppInfo.Version}", userAgent);
    }

    [Fact]
    public async Task IHttpPortDownloadAsyncBridgesCorrectly()
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
            new SynchronousProgress<HttpProgress>(progressReports.Add));

        Assert.True(result.Success);
        Assert.Equal("介面下載", File.ReadAllText(target));
        Assert.NotEmpty(progressReports);
        Assert.Equal(result.BytesProcessed, progressReports[^1].BytesDownloaded);
    }

    [Fact]
    public async Task PostJsonAsyncReturnsResponseOnSuccess()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{\"status\":\"ok\"}", Encoding.UTF8, "application/json"),
        });
        var (handler, http) = fixture;

        string? response = await http.PostJsonAsync(new Uri("https://example.com/api"), "{\"test\":true}");

        Assert.NotNull(response);
        Assert.Equal("{\"status\":\"ok\"}", response);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task PostJsonAsyncRejectsPrivateIpAndReturnsNull()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{\"status\":\"ok\"}", Encoding.UTF8, "application/json"),
        });
        var (handler, http) = fixture;

        string? response = await http.PostJsonAsync(new Uri("https://127.0.0.1/api"), "{}");

        Assert.Null(response);
        Assert.Equal(0, handler.RequestCount);
    }

    [Fact]
    public async Task PostJsonAsyncFailsClosedOnRedirect()
    {
        var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
        redirect.Headers.Location = new Uri("https://example.com/other");
        using var fixture = new DownloadFixture(redirect);
        var (handler, http) = fixture;

        string? response = await http.PostJsonAsync(new Uri("https://example.com/api"), "{}");

        Assert.Null(response);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task PostJsonAsyncReturnsNullWhenResponseOversized()
    {
        var oversizedResponse = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(new byte[100]),
        };
        oversizedResponse.Content.Headers.ContentLength = HttpDownloadClient.MaxJsonBytes + 1;
        using var fixture = new DownloadFixture(oversizedResponse);
        var (handler, http) = fixture;

        string? response = await http.PostJsonAsync(new Uri("https://example.com/api"), "{}");

        Assert.Null(response);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadRejectsIPv6LoopbackAndPrivateIp()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("file.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK));
        var (handler, http) = fixture;

        var exception = await Assert.ThrowsAsync<HttpSecurityException>(() =>
            http.DownloadAsync(new Uri("https://[::1]/download"), target));

        Assert.Contains("非公開", exception.Message);
        Assert.Equal(0, handler.RequestCount);
    }

    [Fact]
    public async Task GetJsonDocumentAsyncRejectsRedirectLimitExceeded()
    {
        var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
        redirect.Headers.Location = new Uri("https://example.com/api");
        using var fixture = new DownloadFixture(
            redirect, redirect, redirect, redirect, redirect,
            redirect, redirect, redirect, redirect, redirect, redirect);
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal("invalid_request", response.ErrorKind);
    }

    [Fact]
    public async Task DownloadResumesFromExistingPartialFileWhenServerReturns206()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "Part1");

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
            expectedHash: Convert.ToHexStringLower(SHA256.HashData("Part1Part2"u8)));

        Assert.True(result.Success);
        Assert.Equal("Part1Part2", await File.ReadAllTextAsync(target));
        Assert.NotNull(handler.LastRequest?.Headers.Range);
        Assert.Equal(5, handler.LastRequest!.Headers.Range!.Ranges.First().From);
    }

    [Fact]
    public async Task DownloadFallsBackToFullDownloadWhenServerReturns200ForRangeRequest()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "OldCorruptContent");

        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("FreshFullContent"u8.ToArray()),
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target);

        Assert.True(result.Success);
        Assert.Equal("FreshFullContent", await File.ReadAllTextAsync(target));
    }

    [Fact]
    public async Task DownloadResetsTemporaryFileWhenServerReturns416()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "StaleBytes");

        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.RequestedRangeNotSatisfiable),
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent("FreshData"u8.ToArray()) });
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { MaxAttempts = 2, RetryDelay = TimeSpan.Zero });

        Assert.True(result.Success);
        Assert.Equal("FreshData", await File.ReadAllTextAsync(target));
        Assert.Equal(2, handler.RequestCount);
    }

    [Fact]
    public async Task DownloadDiscardsStalePartialFileWhenNoExpectedHash()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        await File.WriteAllTextAsync(target + ".part", "StaleBytes");

        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent("FreshContent"u8.ToArray()),
        });
        var (handler, downloader) = fixture;

        var result = await downloader.DownloadAsync(new Uri("https://example.com/file"), target);

        Assert.True(result.Success);
        Assert.Equal("FreshContent", await File.ReadAllTextAsync(target));
        Assert.Null(handler.LastRequest?.Headers.Range);
    }

    [Fact]
    public async Task DownloadDiscardsPartialFileWhenETagChanges()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        string partial = target + ".part";
        await File.WriteAllTextAsync(partial, "OldVersionPart");

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
            expectedHash: Convert.ToHexStringLower(SHA256.HashData("BrandNewVersionContent"u8)));

        Assert.True(result.Success);
        Assert.Equal("BrandNewVersionContent", await File.ReadAllTextAsync(target));
    }

    [Fact]
    public async Task DownloadFailsWithTimeoutWhenBodyStallsBeyondIdleTimeout()
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
            new HttpDownloadOptions { Timeout = TimeSpan.FromMilliseconds(300), MaxAttempts = 1 });

        Assert.False(result.Success);
        Assert.Equal("HTTP 請求逾時", result.Error);
        Assert.False(File.Exists(target));
    }

    [Fact]
    public async Task DownloadSucceedsWhenTotalTimeExceedsTimeoutButDataKeepsArriving()
    {
        using var temp = new TempDirectory("msm-http-");
        string target = temp.Combine("download.bin");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StreamContent(new PacedStream(chunks: 4, delay: TimeSpan.FromMilliseconds(250), stallAfterLastChunk: false)),
        });
        var (_, downloader) = fixture;

        var result = await downloader.DownloadAsync(
            new Uri("https://example.com/file"),
            target,
            new HttpDownloadOptions { Timeout = TimeSpan.FromMilliseconds(600), MaxAttempts = 1 });

        Assert.True(result.Success);
        Assert.Equal(4, new FileInfo(target).Length);
    }

    /// <summary>每次讀出一個位元組並於區塊間延遲；可於最後一塊後永久停滯</summary>
    private sealed class PacedStream(int chunks, TimeSpan delay, bool stallAfterLastChunk) : Stream
    {
        private int _sent;

        public override bool CanRead => true;

        public override bool CanSeek => false;

        public override bool CanWrite => false;

        public override long Length => throw new NotSupportedException();

        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

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

        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        public override void Flush()
        {
        }

        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();

        public override void SetLength(long value) => throw new NotSupportedException();

        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    /// <summary>以佇列回應組成的下載客戶端；Dispose 時釋放 HttpClient</summary>
    private sealed class DownloadFixture : IDisposable
    {
        private readonly HttpClient _client;

        public DownloadFixture(params HttpResponseMessage[] responses)
        {
            Handler = new QueueHandler(responses);
            _client = new HttpClient(Handler);
            Client = new HttpDownloadClient(_client);
        }

        public QueueHandler Handler { get; }

        public HttpDownloadClient Client { get; }

        public void Deconstruct(out QueueHandler handler, out HttpDownloadClient client)
        {
            handler = Handler;
            client = Client;
        }

        public void Dispose() => _client.Dispose();
    }

    private sealed class QueueHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
    {
        private readonly Queue<HttpResponseMessage> _responses = new(responses);

        public int RequestCount { get; private set; }

        public HttpRequestMessage? LastRequest { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            RequestCount++;
            LastRequest = request;
            return Task.FromResult(_responses.Count > 0
                ? _responses.Dequeue()
                : new HttpResponseMessage(HttpStatusCode.InternalServerError));
        }
    }

}
