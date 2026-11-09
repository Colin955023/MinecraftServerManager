using System.Text.Json;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.IntegrationTests;

/// <summary>
/// 測試替身共用：以 GetTextAsync 回應模擬 IHttpPort.GetJsonDocumentAsync
/// </summary>
internal static class TestHttpJson
{
    public static async Task<HttpJsonResponse<JsonDocument>> FromTextAsync(IHttpPort port, Uri uri, CancellationToken cancellationToken)
    {
        string? text = await port.GetTextAsync(uri, cancellationToken).ConfigureAwait(false);
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
}
