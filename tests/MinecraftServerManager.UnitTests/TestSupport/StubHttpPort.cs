using System.Text.Json;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>下載請求內容</summary>
internal sealed record StubDownload(
    Uri Uri,
    string TargetPath,
    IProgress<HttpProgress>? Progress,
    string? ExpectedHash,
    CancellationToken CancellationToken);

/// <summary>測試用 <see cref="IHttpPort"/> 替身；未設定 <see cref="DownloadHandler"/> 時下載會擲出</summary>
internal sealed class StubHttpPort : IHttpPort
{
    private int _requestCount;
    private int _downloadCount;

    public StubHttpPort()
    {
    }

    public StubHttpPort(string? fixedText)
    {
        TextHandler = _ => fixedText;
    }

    public StubHttpPort(Func<Uri, string?> textHandler)
    {
        TextHandler = textHandler;
    }

    /// <summary>建立固定文字回應的替身（null 代表無回應）</summary>
    public static StubHttpPort WithText(string? text) => new(text);

    /// <summary>建立依 URI 決定文字回應的替身；<paramref name="respondToPost"/> 為真時 POST 與 GET 共用同一回應規則</summary>
    public static StubHttpPort WithText(Func<Uri, string?> textHandler, bool respondToPost = false) =>
        new(textHandler) { PostHandler = respondToPost ? (uri, _) => textHandler(uri) : static (_, _) => null };

    /// <summary>建立下載成功的替身：將 <paramref name="content"/> 寫入目標路徑</summary>
    public static StubHttpPort WithDownloadContent(string content) =>
        new()
        {
            DownloadHandler = request =>
            {
                File.WriteAllText(request.TargetPath, content);
                return Task.FromResult(new HttpResult(true, null, content.Length));
            },
        };

    /// <summary>建立下載失敗的替身，不寫入任何檔案</summary>
    public static StubHttpPort WithDownloadFailure(string error) =>
        new() { DownloadHandler = _ => Task.FromResult(new HttpResult(false, error)) };

    /// <summary>GET 文字回應（回傳 null 代表無回應）；可擲出例外以模擬連線失敗</summary>
    public Func<Uri, string?> TextHandler { get; init; } = static _ => null;

    public Func<Uri, string, string?> PostHandler { get; init; } = static (_, _) => null;

    public Func<StubDownload, Task<HttpResult>>? DownloadHandler { get; init; }

    /// <summary>GET 文字請求次數（含 JSON 取得）</summary>
    public int RequestCount => _requestCount;

    public int DownloadCount => _downloadCount;

    public string? LastDownloadExpectedHash { get; private set; }

    public string? LastDownloadExpectedAlgorithm { get; private set; }

    public async Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(Uri uri, CancellationToken cancellationToken = default) =>
        ToJsonResponse(await GetTextAsync(uri, cancellationToken).ConfigureAwait(false));

    private static HttpJsonResponse<JsonDocument> ToJsonResponse(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new HttpJsonResponse<JsonDocument>(404, default, "not_found");
        }

        try
        {
            return new HttpJsonResponse<JsonDocument>(200, JsonDocument.Parse(text), string.Empty);
        }
        catch (JsonException)
        {
            return new HttpJsonResponse<JsonDocument>(200, default, "invalid_response");
        }
    }

    public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default)
    {
        Interlocked.Increment(ref _requestCount);
        if (cancellationToken.IsCancellationRequested)
        {
            return Task.FromCanceled<string?>(cancellationToken);
        }

        try
        {
            return Task.FromResult(TextHandler(uri));
        }
        catch (Exception ex)
        {
            return Task.FromException<string?>(ex);
        }
    }

    public Task<HttpJsonResponse<JsonDocument>> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) =>
        cancellationToken.IsCancellationRequested
            ? Task.FromCanceled<HttpJsonResponse<JsonDocument>>(cancellationToken)
            : Task.FromResult(ToJsonResponse(PostHandler(uri, jsonPayload)));

    public Task<HttpResult> DownloadAsync(
        Uri uri,
        string targetPath,
        IProgress<HttpProgress>? progress = null,
        string? expectedHash = null,
        string expectedHashAlgorithm = "sha256",
        CancellationToken cancellationToken = default)
    {
        Interlocked.Increment(ref _downloadCount);
        LastDownloadExpectedHash = expectedHash;
        LastDownloadExpectedAlgorithm = expectedHashAlgorithm;
        if (DownloadHandler is null)
        {
            throw new NotSupportedException("測試未設定下載行為");
        }

        if (cancellationToken.IsCancellationRequested)
        {
            return Task.FromCanceled<HttpResult>(cancellationToken);
        }

        return DownloadHandler(new StubDownload(uri, targetPath, progress, expectedHash, cancellationToken));
    }
}
