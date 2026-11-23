using System.Net;
using System.Text;
using MinecraftServerManager.Infrastructure.Http;

namespace MinecraftServerManager.UnitTests.Http;

public sealed class HttpRequestTests
{
    [Fact]
    public void ValidateStatic_InsecureOrPrivateTarget_Rejects()
    {
        Assert.Throws<HttpSecurityException>(static () => HttpUrlPolicy.ValidateStatic(new Uri("http://example.com/file")));
        Assert.Throws<HttpSecurityException>(static () => HttpUrlPolicy.ValidateStatic(new Uri("https://user:pass@example.com/file")));
        Assert.Throws<HttpSecurityException>(static () => HttpUrlPolicy.ValidateStatic(new Uri("https://127.0.0.1/file")));
    }

    [Fact]
    public async Task ConnectAsync_PrivateDnsResult_RejectsBeforeConnecting()
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
                TestContext.Current.CancellationToken));

        Assert.Contains("非公開", exception.Message);
        Assert.Equal(1, resolveCount);
    }

    [Fact]
    public async Task GetJsonDocumentAsync_ValidResponse_ReturnsDocument()
    {
        string json = """{"name": "Minecraft", "version": 2}""";
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        });
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

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
    public async Task GetJsonDocumentAsync_ErrorStatus_ClassifiesFailure(HttpStatusCode statusCode, string expectedErrorKind)
    {
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(statusCode),
            new HttpResponseMessage(statusCode),
            new HttpResponseMessage(statusCode));
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

        Assert.False(response.IsSuccess);
        Assert.Equal((int)statusCode, response.StatusCode);
        Assert.Equal(expectedErrorKind, response.ErrorKind);
        Assert.Null(response.Payload);
    }

    [Fact]
    public async Task GetJsonDocumentAsync_RateLimited_RetriesThenFails()
    {
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.TooManyRequests),
            new HttpResponseMessage(HttpStatusCode.TooManyRequests),
            new HttpResponseMessage(HttpStatusCode.TooManyRequests));
        var (handler, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

        Assert.False(response.IsSuccess);
        Assert.Equal(429, response.StatusCode);
        Assert.Equal("rate_limited", response.ErrorKind);
        Assert.Equal(3, handler.RequestCount);
    }

    /// <summary>讀取回應內容時擲出 IOException（模擬連線中途中斷）</summary>
    private sealed class IoFailingContent : HttpContent
    {
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            Task.FromException(new IOException("模擬連線中斷"));

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }

        protected override Task<Stream> CreateContentReadStreamAsync() =>
            Task.FromException<Stream>(new IOException("模擬連線中斷"));
    }

    [Fact]
    public async Task GetTextAsync_ResponseStreamIOException_RetriesThenSucceeds()
    {
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new IoFailingContent() },
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("完成", Encoding.UTF8, "text/plain") });
        var (handler, http) = fixture;

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"), TestContext.Current.CancellationToken);

        Assert.Equal("完成", text);
        Assert.Equal(2, handler.RequestCount);
    }

    [Fact]
    public async Task GetTextAsync_ResponseStreamIOExceptionEveryAttempt_FailsAfterMaxAttempts()
    {
        using var fixture = new DownloadFixture(
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new IoFailingContent() },
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new IoFailingContent() },
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new IoFailingContent() });
        var (handler, http) = fixture;

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"), TestContext.Current.CancellationToken);

        Assert.Null(text);
        Assert.Equal(3, handler.RequestCount);
    }

    [Fact]
    public async Task GetJsonDocumentAsync_InvalidJson_ReturnsFailure()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("not a valid json", Encoding.UTF8, "application/json"),
        });
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

        Assert.False(response.IsSuccess);
        Assert.Equal("invalid_response", response.ErrorKind);
    }

    [Fact]
    public async Task GetJsonDocumentAsync_CompressedContent_Succeeds()
    {
        var content = new StringContent("""{"name": "test", "version": 1}""", Encoding.UTF8, "application/json");
        content.Headers.ContentEncoding.Add("gzip");
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = content,
        });
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

        Assert.True(response.IsSuccess);
        Assert.NotNull(response.Payload);
        using var doc = response.Payload;
        Assert.Equal("test", doc.RootElement.GetProperty("name").GetString());
        Assert.Equal(1, doc.RootElement.GetProperty("version").GetInt32());
    }

    [Fact]
    public async Task GetTextAsync_WithinLimit_ReturnsContent()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("純文字內容", Encoding.UTF8, "text/plain"),
        });
        var (_, http) = fixture;

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"), TestContext.Current.CancellationToken);

        Assert.Equal("純文字內容", text);
    }

    [Fact]
    public async Task GetTextAsync_OversizedContent_ReturnsNull()
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(new byte[100]),
        };
        response.Content.Headers.ContentLength = HttpDownloadClient.MaxTextBytes + 1;
        using var fixture = new DownloadFixture(response);
        var (_, http) = fixture;

        string? text = await http.GetTextAsync(new Uri("https://example.com/text"), TestContext.Current.CancellationToken);

        Assert.Null(text);
    }

    [Fact]
    public async Task SendAsync_NoUserAgent_InjectsDefault()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        });
        var (handler, http) = fixture;

        await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

        Assert.NotNull(handler.LastRequest);
        string userAgent = handler.LastRequest.Headers.UserAgent.ToString();
        Assert.Contains($"MinecraftServerManager/{Core.AppInfo.Version}", userAgent);
    }

    [Fact]
    public async Task PostJsonAsync_Success_ReturnsResponse()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{\"status\":\"ok\"}", Encoding.UTF8, "application/json"),
        });
        var (handler, http) = fixture;

        using var response = await http.PostJsonAsync(new Uri("https://example.com/api"), "{\"test\":true}", TestContext.Current.CancellationToken);

        Assert.True(response.IsSuccess);
        Assert.Equal("ok", response.Payload!.RootElement.GetProperty("status").GetString());
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task PostJsonAsync_PrivateIp_Rejects()
    {
        using var fixture = new DownloadFixture(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{\"status\":\"ok\"}", Encoding.UTF8, "application/json"),
        });
        var (handler, http) = fixture;

        using var response = await http.PostJsonAsync(new Uri("https://127.0.0.1/api"), "{}", TestContext.Current.CancellationToken);

        Assert.Equal("invalid_request", response.ErrorKind);
        Assert.Equal(0, handler.RequestCount);
    }

    [Fact]
    public async Task PostJsonAsync_Redirect_FailsClosed()
    {
        var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
        redirect.Headers.Location = new Uri("https://example.com/other");
        using var fixture = new DownloadFixture(redirect);
        var (handler, http) = fixture;

        using var response = await http.PostJsonAsync(new Uri("https://example.com/api"), "{}", TestContext.Current.CancellationToken);

        Assert.False(response.IsSuccess);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task PostJsonAsync_OversizedResponse_ReportsInvalidResponse()
    {
        var oversizedResponse = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(new byte[100]),
        };
        oversizedResponse.Content.Headers.ContentLength = HttpDownloadClient.MaxJsonBytes + 1;
        using var fixture = new DownloadFixture(oversizedResponse);
        var (handler, http) = fixture;

        using var response = await http.PostJsonAsync(new Uri("https://example.com/api"), "{}", TestContext.Current.CancellationToken);

        Assert.Equal("invalid_response", response.ErrorKind);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task GetJsonDocumentAsync_RedirectLimitExceeded_Rejects()
    {
        var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
        redirect.Headers.Location = new Uri("https://example.com/api");
        using var fixture = new DownloadFixture(
            redirect, redirect, redirect, redirect, redirect,
            redirect, redirect, redirect, redirect, redirect, redirect);
        var (_, http) = fixture;

        var response = await http.GetJsonDocumentAsync(new Uri("https://example.com/api"), TestContext.Current.CancellationToken);

        Assert.False(response.IsSuccess);
        Assert.Equal("invalid_request", response.ErrorKind);
    }

    [Fact]
    public async Task GetTextAsync_RetryAfterDate_UsesInjectedClockForDelay()
    {
        // 依注入時鐘 Retry-After 等於「現在」應立即重試；若誤用系統時鐘會等待上限 1 分鐘
        var now = new DateTimeOffset(2100, 1, 1, 0, 0, 0, TimeSpan.Zero);
        var retry = new HttpResponseMessage(HttpStatusCode.ServiceUnavailable);
        retry.Headers.RetryAfter = new System.Net.Http.Headers.RetryConditionHeaderValue(now);
        using var fixture = new DownloadFixture(
            new FixedNowTimeProvider(now),
            retry,
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("ok") });

        string? text = await fixture.Client.GetTextAsync(new Uri("https://example.com/a.txt"), TestContext.Current.CancellationToken)
            .WaitAsync(TimeSpan.FromSeconds(10), TestContext.Current.CancellationToken);

        Assert.Equal("ok", text);
    }
}
