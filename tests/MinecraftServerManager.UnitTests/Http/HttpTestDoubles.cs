using System.Net;
using MinecraftServerManager.Infrastructure.Http;

namespace MinecraftServerManager.UnitTests.Http;

/// <summary>固定目前時間的時間來源（計時器仍使用系統時鐘）</summary>
internal sealed class FixedNowTimeProvider(DateTimeOffset now) : TimeProvider
{
    public override DateTimeOffset GetUtcNow() => now;
}

/// <summary>非同步唯讀串流基礎類別，提供預設虛擬成員簡化測試串流實作</summary>
internal abstract class AsyncReadOnlyStream : Stream
{
    public override bool CanRead => true;
    public override bool CanSeek => false;
    public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    public override void Flush() { }
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
}

/// <summary>測試用 HTTP 回應工廠</summary>
internal static class HttpResponses
{
    public static HttpResponseMessage Ok(byte[] content) =>
        new(HttpStatusCode.OK) { Content = new ByteArrayContent(content) };

    public static HttpResponseMessage Ok(string text) =>
        Ok(System.Text.Encoding.UTF8.GetBytes(text));

    public static HttpResponseMessage Partial(byte[] content, long from, long to, long total)
    {
        var response = new HttpResponseMessage(HttpStatusCode.PartialContent)
        {
            Content = new ByteArrayContent(content)
        };
        response.Content.Headers.ContentRange = new System.Net.Http.Headers.ContentRangeHeaderValue(from, to, total);
        return response;
    }

    public static HttpResponseMessage Redirect(string targetUrl, HttpStatusCode status = HttpStatusCode.Found)
    {
        var response = new HttpResponseMessage(status);
        response.Headers.Location = new Uri(targetUrl);
        return response;
    }
}

/// <summary>以佇列回應組成的下載客戶端；Dispose 時釋放 HttpClient 與專屬暫存目錄</summary>
internal sealed class DownloadFixture : IDisposable
{
    private readonly HttpClient _client;
    private readonly TempDirectory? _temp;

    public TempDirectory Temp => _temp ?? throw new InvalidOperationException("未由 Fixture 建立暫存目錄");

    public string TargetPath => Temp.Combine("download.bin");

    public DownloadFixture(params HttpResponseMessage[] responses)
        : this(TimeProvider.System, responses)
    {
    }

    public DownloadFixture(TimeProvider timeProvider, params HttpResponseMessage[] responses)
    {
        _temp = new TempDirectory("msm-http-");
        Handler = new QueueHandler(responses);
        _client = new HttpClient(Handler);
        Client = new HttpDownloadClient(_client, timeProvider);
    }

    public QueueHandler Handler { get; }

    public HttpDownloadClient Client { get; }

    public void Deconstruct(out QueueHandler handler, out HttpDownloadClient client)
    {
        handler = Handler;
        client = Client;
    }

    public void Dispose()
    {
        _client.Dispose();
        _temp?.Dispose();
    }
}

internal sealed class QueueHandler(params HttpResponseMessage[] responses) : HttpMessageHandler
{
    private readonly Queue<HttpResponseMessage> _responses = new(responses);

    public int RequestCount { get; private set; }

    public HttpRequestMessage? LastRequest { get; private set; }

    /// <summary>設定時每次送出請求皆擲出此例外（模擬連線階段失敗）</summary>
    public Exception? SendException { get; init; }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        RequestCount++;
        LastRequest = request;
        if (SendException is not null)
        {
            return Task.FromException<HttpResponseMessage>(SendException);
        }

        return Task.FromResult(_responses.Count > 0
            ? _responses.Dequeue()
            : new HttpResponseMessage(HttpStatusCode.InternalServerError));
    }
}
