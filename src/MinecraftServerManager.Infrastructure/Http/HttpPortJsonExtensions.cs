using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Http;

/// <summary><see cref="IHttpPort"/> 的 JSON 讀取共用擴充方法</summary>
internal static class HttpPortJsonExtensions
{
    /// <summary>取得遠端 JSON 文件；非成功回應或非取消例外時記錄警告並回傳 null（呼叫端負責處置）</summary>
    public static async Task<JsonDocument?> TryGetJsonDocumentAsync(
        this IHttpPort httpPort,
        Uri uri,
        ComponentLogger logger,
        string failureMessage,
        CancellationToken cancellationToken)
    {
        try
        {
            var response = await httpPort.GetJsonDocumentAsync(uri, cancellationToken).ConfigureAwait(false);
            if (response.IsSuccess && response.Payload is not null)
            {
                return response.Payload;
            }

            response.Dispose();
            return null;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger.Warning(ex, failureMessage, uri);
            return null;
        }
    }
}
