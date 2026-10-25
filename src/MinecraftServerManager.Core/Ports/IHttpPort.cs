using System.Text.Json;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// HTTP 傳輸進度通知
/// </summary>
public sealed record HttpProgress(long BytesDownloaded, long TotalBytes);

/// <summary>
/// HTTP 操作結果
/// </summary>
public sealed record HttpResult(bool Success, string? Error = null, long BytesProcessed = 0);

/// <summary>
/// 保留 HTTP 狀態與失敗類型的 JSON 回應封裝
/// </summary>
public sealed record HttpJsonResponse<T>(
    int? StatusCode,
    T? Payload,
    string ErrorKind = "")
{
    public bool IsSuccess => StatusCode is >= 200 and <= 299 && Payload != null;
}

/// <summary>
/// HTTP 傳輸與下載服務連接埠契約
/// </summary>
public interface IHttpPort
{
    /// <summary>
    /// 安全下載檔案至指定路徑並執行雜湊與邊界校驗
    /// </summary>
    public Task<HttpResult> DownloadAsync(
        Uri uri,
        string targetPath,
        IProgress<HttpProgress>? progress = null,
        string? expectedHash = null,
        string expectedHashAlgorithm = "sha256",
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 安全取得遠端 JSON 資料並反序列化
    /// </summary>
    public Task<HttpJsonResponse<T>> GetJsonAsync<T>(
        Uri uri,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 安全取得遠端 JSON 文件並以串流解析（呼叫端負責處置 JsonDocument）
    /// </summary>
    public Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(
        Uri uri,
        CancellationToken cancellationToken = default) => GetJsonDocumentFallbackAsync(this, uri, cancellationToken);

    /// <summary>
    /// 安全取得遠端文字內容
    /// </summary>
    public Task<string?> GetTextAsync(
        Uri uri,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 安全傳送 POST JSON 請求並取得遠端文字回應
    /// </summary>
    public Task<string?> PostJsonAsync(
        Uri uri,
        string jsonPayload,
        CancellationToken cancellationToken = default);

    private static async Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentFallbackAsync(
        IHttpPort port,
        Uri uri,
        CancellationToken cancellationToken)
    {
        string? text = await port.GetTextAsync(uri, cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(text))
        {
            return new HttpJsonResponse<JsonDocument>(404, default, "not_found");
        }

        try
        {
            var doc = JsonDocument.Parse(text);
            return new HttpJsonResponse<JsonDocument>(200, doc, string.Empty);
        }
        catch (JsonException)
        {
            return new HttpJsonResponse<JsonDocument>(200, default, "invalid_response");
        }
    }
}

