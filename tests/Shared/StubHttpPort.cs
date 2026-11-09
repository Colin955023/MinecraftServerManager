using System.Text.Json;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.TestSupport;

/// <summary>下載請求內容</summary>
internal sealed record StubDownload(
    Uri Uri,
    string TargetPath,
    IProgress<HttpProgress>? Progress,
    string? ExpectedHash,
    CancellationToken CancellationToken);

/// <summary>
/// 測試共用 <see cref="IHttpPort"/> 替身：以委派模擬文字、POST 與下載回應，並記錄呼叫次數。
/// 未設定 <see cref="DownloadHandler"/> 時下載視為不應發生並擲出例外；JSON 取得以 <see cref="GetTextAsync"/> 回應轉換。
/// </summary>
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

    /// <summary>GET 文字回應（回傳 null 代表無回應）；可擲出例外以模擬連線失敗</summary>
    public Func<Uri, string?> TextHandler { get; init; } = static _ => null;

    /// <summary>POST JSON 回應</summary>
    public Func<Uri, string, string?> PostHandler { get; init; } = static (_, _) => null;

    /// <summary>下載行為；未設定時擲出 <see cref="NotSupportedException"/></summary>
    public Func<StubDownload, Task<HttpResult>>? DownloadHandler { get; init; }

    /// <summary>GET 文字請求次數（含 JSON 取得）</summary>
    public int RequestCount => _requestCount;

    /// <summary>下載請求次數</summary>
    public int DownloadCount => _downloadCount;

    public string? LastDownloadExpectedHash { get; private set; }

    public string? LastDownloadExpectedAlgorithm { get; private set; }

    public async Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(Uri uri, CancellationToken cancellationToken = default)
    {
        string? text = await GetTextAsync(uri, cancellationToken).ConfigureAwait(false);
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
        try
        {
            return Task.FromResult(TextHandler(uri));
        }
        catch (Exception ex)
        {
            return Task.FromException<string?>(ex);
        }
    }

    public Task<string?> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) =>
        Task.FromResult(PostHandler(uri, jsonPayload));

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

        return DownloadHandler(new StubDownload(uri, targetPath, progress, expectedHash, cancellationToken));
    }
}
