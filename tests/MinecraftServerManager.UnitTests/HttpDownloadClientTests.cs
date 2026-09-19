using System.Net;
using System.Net.Http;
using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Http;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class HttpDownloadClientTests
{
    [Fact]
    public void UrlPolicyRejectsInsecureAndPrivateTargets()
    {
        Assert.Throws<HttpSecurityException>(() => HttpUrlPolicy.ValidateStatic(new Uri("http://example.com/file")));
        Assert.Throws<HttpSecurityException>(() => HttpUrlPolicy.ValidateStatic(new Uri("https://user:pass@example.com/file")));
        Assert.Throws<HttpSecurityException>(() => HttpUrlPolicy.ValidateStatic(new Uri("https://127.0.0.1/file")));
    }

    [Fact]
    public async Task DownloadStreamsToAtomicTargetAndReportsProgress()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string target = Path.Combine(root, "download.bin");
            var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent("下載內容"u8.ToArray()),
            });
            using var client = new HttpClient(handler);
            var downloader = new HttpDownloadClient(client, PublicResolver);
            var progress = new List<HttpDownloadProgress>();

            var result = await downloader.DownloadAsync(
                new Uri("https://example.com/file"),
                target,
                new HttpDownloadOptions { MaxBytes = 1024 },
                new Progress<HttpDownloadProgress>(progress.Add));

            Assert.True(result.Success);
            Assert.Equal("下載內容", File.ReadAllText(target));
            Assert.NotEmpty(progress);
            Assert.Equal(result.BytesDownloaded, progress[^1].BytesDownloaded);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task DownloadRejectsOversizedResponseWithoutOverwritingTarget()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string target = Path.Combine(root, "download.bin");
            File.WriteAllText(target, "保留內容");
            var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent("太大的內容"u8.ToArray()),
            });
            using var client = new HttpClient(handler);
            var downloader = new HttpDownloadClient(client, PublicResolver);

            var result = await downloader.DownloadAsync(
                new Uri("https://example.com/file"),
                target,
                new HttpDownloadOptions { MaxBytes = 1 });

            Assert.False(result.Success);
            Assert.Equal("保留內容", File.ReadAllText(target));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task DownloadRejectsCompressedResponseWithoutOverwritingTarget()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string target = Path.Combine(root, "download.bin");
            File.WriteAllText(target, "保留內容");
            var content = new ByteArrayContent("壓縮內容"u8.ToArray());
            content.Headers.ContentEncoding.Add("gzip");
            var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = content,
            });
            using var client = new HttpClient(handler);
            var downloader = new HttpDownloadClient(client, PublicResolver);

            var result = await downloader.DownloadAsync(
                new Uri("https://example.com/file"),
                target,
                new HttpDownloadOptions { MaxBytes = 1024 });

            Assert.False(result.Success);
            Assert.Equal("不支援壓縮 HTTP response", result.Error);
            Assert.Equal("保留內容", File.ReadAllText(target));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task DownloadRetriesTransientStatus()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string target = Path.Combine(root, "download.bin");
            var handler = new QueueHandler(
                new HttpResponseMessage(HttpStatusCode.ServiceUnavailable),
                new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent("完成"u8.ToArray()) });
            using var client = new HttpClient(handler);
            var downloader = new HttpDownloadClient(client, PublicResolver);

            var result = await downloader.DownloadAsync(
                new Uri("https://example.com/file"),
                target,
                new HttpDownloadOptions { MaxAttempts = 2, RetryDelay = TimeSpan.Zero });

            Assert.True(result.Success);
            Assert.Equal(2, handler.RequestCount);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task DownloadRejectsUnsafeRedirect()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string target = Path.Combine(root, "download.bin");
            var redirect = new HttpResponseMessage(HttpStatusCode.Found);
            redirect.Headers.Location = new Uri("http://example.com/file");
            var handler = new QueueHandler(redirect);
            using var client = new HttpClient(handler);
            var downloader = new HttpDownloadClient(client, PublicResolver);

            var result = await downloader.DownloadAsync(new Uri("https://example.com/file"), target);

            Assert.False(result.Success);
            Assert.Equal(1, handler.RequestCount);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private sealed record TestModel(string Name, int Version);

    [Fact]
    public async Task GetJsonAsyncDeserializesValidResponse()
    {
        string json = """{"name": "Minecraft", "version": 2}""";
        var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        });
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        var response = await http.GetJsonAsync<TestModel>(new Uri("https://example.com/api"));

        Assert.True(response.IsSuccess);
        Assert.Equal(200, response.StatusCode);
        Assert.NotNull(response.Payload);
        Assert.Equal("Minecraft", response.Payload.Name);
        Assert.Equal(2, response.Payload.Version);
        Assert.Empty(response.ErrorKind);
    }

    [Theory]
    [InlineData(HttpStatusCode.NotFound, "not_found")]
    [InlineData(HttpStatusCode.BadRequest, "invalid_request")]
    [InlineData(HttpStatusCode.InternalServerError, "transient")]
    public async Task GetJsonAsyncClassifiesStatusCodes(HttpStatusCode statusCode, string expectedErrorKind)
    {
        var handler = new QueueHandler(
            new HttpResponseMessage(statusCode),
            new HttpResponseMessage(statusCode),
            new HttpResponseMessage(statusCode));
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        var response = await http.GetJsonAsync<TestModel>(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal((int)statusCode, response.StatusCode);
        Assert.Equal(expectedErrorKind, response.ErrorKind);
        Assert.Null(response.Payload);
    }

    [Fact]
    public async Task GetJsonAsyncRetriesRateLimitedThenFails()
    {
        var handler = new QueueHandler(
            new HttpResponseMessage(HttpStatusCode.TooManyRequests),
            new HttpResponseMessage(HttpStatusCode.TooManyRequests),
            new HttpResponseMessage(HttpStatusCode.TooManyRequests));
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        var response = await http.GetJsonAsync<TestModel>(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal(429, response.StatusCode);
        Assert.Equal("rate_limited", response.ErrorKind);
        Assert.Equal(3, handler.RequestCount);
    }

    [Fact]
    public async Task GetJsonAsyncRejectsInvalidJson()
    {
        var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("not a valid json", Encoding.UTF8, "application/json"),
        });
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        var response = await http.GetJsonAsync<TestModel>(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal("invalid_response", response.ErrorKind);
    }

    [Fact]
    public async Task GetJsonAsyncRejectsCompressedResponse()
    {
        var content = new StringContent("""{"name": "test", "version": 1}""", Encoding.UTF8, "application/json");
        content.Headers.ContentEncoding.Add("gzip");
        var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = content,
        });
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        var response = await http.GetJsonAsync<TestModel>(new Uri("https://example.com/api"));

        Assert.False(response.IsSuccess);
        Assert.Equal("invalid_response", response.ErrorKind);
    }

    [Fact]
    public async Task GetTextAsyncReturnsContentAndEnforcesLimits()
    {
        var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("純文字內容", Encoding.UTF8, "text/plain"),
        });
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

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
        var handler = new QueueHandler(response);
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"));

        Assert.Null(text);
    }

    [Fact]
    public async Task RequestInjectsDefaultUserAgent()
    {
        var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        });
        using var client = new HttpClient(handler);
        var http = new HttpDownloadClient(client, PublicResolver);

        await http.GetJsonAsync<TestModel>(new Uri("https://example.com/api"));

        Assert.NotNull(handler.LastRequest);
        string userAgent = handler.LastRequest.Headers.UserAgent.ToString();
        Assert.Contains("MinecraftServerManager/2.0.0", userAgent);
    }

    [Fact]
    public async Task IHttpPortDownloadAsyncBridgesCorrectly()
    {
        string root = CreateTemporaryDirectory();
        try
        {
            string target = Path.Combine(root, "port_download.bin");
            var handler = new QueueHandler(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent("介面下載"u8.ToArray()),
            });
            using var client = new HttpClient(handler);
            IHttpPort http = new HttpDownloadClient(client, PublicResolver);
            var progressReports = new List<HttpProgress>();

            var result = await http.DownloadAsync(
                new Uri("https://example.com/port-file"),
                target,
                new SyncProgress<HttpProgress>(progressReports.Add));

            Assert.True(result.Success);
            Assert.Equal("介面下載", File.ReadAllText(target));
            Assert.NotEmpty(progressReports);
            Assert.Equal(result.BytesProcessed, progressReports[^1].BytesDownloaded);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static Task<IPAddress[]> PublicResolver(string _, CancellationToken __) =>
        Task.FromResult(new[] { IPAddress.Parse("93.184.216.34") });

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-http-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
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

    private sealed class SyncProgress<T>(Action<T> action) : IProgress<T>
    {
        public void Report(T value) => action(value);
    }
}
