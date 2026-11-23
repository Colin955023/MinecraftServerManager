using MinecraftServerManager.Core;

namespace MinecraftServerManager.Infrastructure.Http;

public sealed partial class HttpDownloadClient
{
    private async Task<HttpResponseMessage> SendAndDisposeRequestAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        using (request)
        {
            return await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<HttpResponseMessage> SendWithRedirectsAsync(
        Uri initialUri,
        int maxRedirects,
        CancellationToken cancellationToken,
        long? fromByte = null,
        string? ifRangeTag = null)
    {
        var currentUri = initialUri;
        for (int redirect = 0; ; redirect++)
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, currentUri);
            EnsureUserAgent(request);
            if (fromByte.HasValue && fromByte.Value >= 0)
            {
                request.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(fromByte.Value, null);
                if (!string.IsNullOrWhiteSpace(ifRangeTag))
                {
                    request.Headers.IfRange = new System.Net.Http.Headers.RangeConditionHeaderValue(ifRangeTag);
                }
            }
            var response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            if (!RedirectStatuses.Contains(response.StatusCode))
            {
                return response;
            }

            if (redirect >= maxRedirects || response.Headers.Location is null)
            {
                response.Dispose();
                throw new HttpSecurityException("HTTP redirect 超過安全上限或缺少 Location");
            }

            var nextUri = response.Headers.Location.IsAbsoluteUri
                ? response.Headers.Location
                : new Uri(currentUri, response.Headers.Location);
            response.Dispose();
            HttpUrlPolicy.ValidateStatic(nextUri);
            currentUri = nextUri;
        }
    }

    private void EnsureUserAgent(HttpRequestMessage request)
    {
        if (request.Headers.UserAgent.Count == 0 && _client.DefaultRequestHeaders.UserAgent.Count == 0)
        {
            request.Headers.UserAgent.ParseAdd($"{AppInfo.AppId}/{AppInfo.Version} (+{AppInfo.RepositoryUrl})");
        }
    }
}
