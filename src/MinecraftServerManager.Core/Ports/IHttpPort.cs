using System.Text.Json;
using MinecraftServerManager.Core.Utilities;

namespace MinecraftServerManager.Core.Ports;

/// <summary>HTTP 傳輸進度通知</summary>
public sealed record HttpProgress(long BytesDownloaded, long TotalBytes);

/// <summary>HTTP 操作結果</summary>
public sealed record HttpResult(bool Success, string? Error = null, long BytesProcessed = 0);

/// <summary>保留 HTTP 狀態與失敗類型的 JSON 回應封裝；處置時一併釋放可處置之內容</summary>
public sealed record HttpJsonResponse<T>(
    int? StatusCode,
    T? Payload,
    string ErrorKind = "") : IDisposable
{
    public bool IsSuccess => StatusCode is >= 200 and <= 299 && Payload is not null;

    public void Dispose()
    {
        if (Payload is IDisposable disposable)
        {
            disposable.Dispose();
        }
    }
}

/// <summary>HTTP 傳輸與下載服務連接埠契約</summary>
public interface IHttpPort
{
    /// <summary>安全下載檔案至指定路徑並執行雜湊與邊界驗證</summary>
    public Task<HttpResult> DownloadAsync(
        Uri uri,
        string targetPath,
        IProgress<HttpProgress>? progress = null,
        string? expectedHash = null,
        string expectedHashAlgorithm = HashAlgorithmNames.Sha256,
        CancellationToken cancellationToken = default);

    /// <summary>取得遠端 JSON 文件（呼叫端負責處置）</summary>
    public Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(
        Uri uri,
        CancellationToken cancellationToken = default);

    /// <summary>安全取得遠端文字內容</summary>
    public Task<string?> GetTextAsync(
        Uri uri,
        CancellationToken cancellationToken = default);

    /// <summary>安全傳送 POST JSON 請求並取得 JSON 文件回應（呼叫端負責處置）</summary>
    public Task<HttpJsonResponse<JsonDocument>> PostJsonAsync(
        Uri uri,
        string jsonPayload,
        CancellationToken cancellationToken = default);
}
