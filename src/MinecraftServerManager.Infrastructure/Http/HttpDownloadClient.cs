using System.Buffers;
using System.Collections.Frozen;
using System.Net;
using System.Text;
using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Http;

public sealed record HttpDownloadOptions
{
    public static readonly HttpDownloadOptions Default = new();

    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(60);

    public int MaxAttempts { get; init; } = 3;

    public int MaxRedirects { get; init; } = 10;

    public long MaxBytes { get; init; } = 512L * 1024 * 1024;

    public TimeSpan RetryDelay { get; init; } = TimeSpan.FromMilliseconds(100);

    public bool EnableRangeResumption { get; init; } = true;
}

public sealed partial class HttpDownloadClient : IHttpPort
{
    internal const long MaxJsonBytes = 16L * 1024 * 1024;
    internal const long MaxTextBytes = 64L * 1024 * 1024;
    private static readonly TimeSpan MaxRetryDelay = TimeSpan.FromMinutes(1);

    private static readonly FrozenSet<HttpStatusCode> RetryableStatuses = FrozenSet.Create(
        HttpStatusCode.RequestTimeout,
        HttpStatusCode.TooManyRequests,
        HttpStatusCode.InternalServerError,
        HttpStatusCode.BadGateway,
        HttpStatusCode.ServiceUnavailable,
        HttpStatusCode.GatewayTimeout);

    private static readonly FrozenSet<HttpStatusCode> RedirectStatuses = FrozenSet.Create(
        HttpStatusCode.MovedPermanently,
        HttpStatusCode.Found,
        HttpStatusCode.SeeOther,
        HttpStatusCode.TemporaryRedirect,
        HttpStatusCode.PermanentRedirect);

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(HttpDownloadClient));

    private readonly HttpClient _client;
    private readonly TimeProvider _timeProvider;
    private const int DefaultRequestMaxAttempts = 3;
    private const int DefaultRequestMaxRedirects = 10;
    private static readonly TimeSpan ProgressReportInterval = TimeSpan.FromMilliseconds(100);
    private static readonly TimeSpan DefaultRequestRetryDelay = TimeSpan.FromMilliseconds(100);
    private static readonly TimeSpan DefaultRequestTimeout = TimeSpan.FromSeconds(30);

    private enum AttemptFailureKind
    {
        Security,
        Transport,
        Timeout,
        Exhausted,
    }

    private readonly record struct AttemptCycle<TResult>(bool ShouldRetry, TResult Result)
    {
        public static AttemptCycle<TResult> Retry() => new(true, default!);
        public static AttemptCycle<TResult> Finish(TResult result) => new(false, result);
    }

    public HttpDownloadClient(HttpClient client, TimeProvider timeProvider)
    {
        ArgumentNullException.ThrowIfNull(client);
        ArgumentNullException.ThrowIfNull(timeProvider);
        _client = client;
        _timeProvider = timeProvider;
    }

    /// <summary>安全下載檔案（使用預設下載選項）</summary>
    Task<HttpResult> IHttpPort.DownloadAsync(
        Uri uri,
        string targetPath,
        IProgress<HttpProgress>? progress,
        string? expectedHash,
        string expectedHashAlgorithm,
        CancellationToken cancellationToken) =>
        DownloadAsync(uri, targetPath, options: null, progress, expectedHash, expectedHashAlgorithm, cancellationToken);

    /// <summary>執行通用重試與逾時迴圈，集中處理傳輸與安全例外</summary>
    private async Task<TResult> ExecuteAttemptLoopAsync<TResult>(
        Uri uri,
        int maxAttempts,
        TimeSpan timeout,
        TimeSpan retryDelay,
        string operationName,
        Func<int, CancellationTokenSource, CancellationToken, Task<AttemptCycle<TResult>>> attemptAction,
        Func<AttemptFailureKind, string, TResult> failureFactory,
        CancellationToken cancellationToken)
    {
        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            using var attemptTimeout = new CancellationTokenSource(timeout, _timeProvider);
            using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, attemptTimeout.Token);

            try
            {
                var cycle = await attemptAction(attempt, attemptTimeout, attemptCancellation.Token).ConfigureAwait(false);
                if (!cycle.ShouldRetry)
                {
                    return cycle.Result;
                }
            }
            catch (HttpSecurityException exception)
            {
                Logger.Warning(exception, "{Operation}遭安全原則拒絕: {Uri}", operationName, uri);
                return failureFactory(AttemptFailureKind.Security, exception.Message);
            }
            catch (HttpRequestException exception) when (exception.InnerException is HttpSecurityException security)
            {
                Logger.Warning(exception, "{Operation}連線遭安全原則拒絕: {Uri}", operationName, uri);
                return failureFactory(AttemptFailureKind.Security, security.Message);
            }
            catch (Exception exception) when (IsRetryableTransportException(exception) && attempt < maxAttempts)
            {
                Logger.Warning(exception, "{Operation}中斷，準備進行第 {Attempt} 次重試: {Uri}", operationName, attempt + 1, uri);
                await Task.Delay(ScaleDelay(retryDelay, attempt), _timeProvider, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception exception) when (IsRetryableTransportException(exception))
            {
                Logger.Warning(exception, "{Operation}重試後仍失敗: {Uri}", operationName, uri);
                return failureFactory(AttemptFailureKind.Transport, exception.Message);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < maxAttempts)
            {
                Logger.Information("{Operation}逾時，準備進行第 {Attempt} 次重試: {Uri}", operationName, attempt + 1, uri);
                await Task.Delay(ScaleDelay(retryDelay, attempt), _timeProvider, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException exception) when (!cancellationToken.IsCancellationRequested)
            {
                Logger.Warning(exception, "{Operation}逾時: {Uri}", operationName, uri);
                return failureFactory(AttemptFailureKind.Timeout, "HTTP 請求逾時");
            }
        }

        return failureFactory(AttemptFailureKind.Exhausted, "重試次數已用盡");
    }

    /// <summary>執行具備重試、重新導向與逾時控制的 HTTP 請求</summary>
    private async Task<TResult> ExecuteRequestWithRetryAsync<TResult>(
        Uri uri,
        Func<HttpResponseMessage, CancellationToken, Task<TResult>> responseHandler,
        Func<string, int?, TResult> failureFactory,
        CancellationToken cancellationToken,
        Func<CancellationToken, Task<HttpResponseMessage>>? requestSender = null)
    {
        try
        {
            HttpUrlPolicy.ValidateStatic(uri);
        }
        catch (HttpSecurityException)
        {
            return failureFactory("invalid_request", null);
        }

        return await ExecuteAttemptLoopAsync(
            uri,
            DefaultRequestMaxAttempts,
            DefaultRequestTimeout,
            DefaultRequestRetryDelay,
            "HTTP 請求",
            async (attempt, _, token) =>
            {
                var response = requestSender is not null
                    ? await requestSender(token).ConfigureAwait(false)
                    : await SendWithRedirectsAsync(uri, DefaultRequestMaxRedirects, token).ConfigureAwait(false);
                using (response)
                {
                    if (RetryableStatuses.Contains(response.StatusCode) && attempt < DefaultRequestMaxAttempts)
                    {
                        await DelayBeforeRetryAsync(response, DefaultRequestRetryDelay, attempt, cancellationToken).ConfigureAwait(false);
                        return AttemptCycle<TResult>.Retry();
                    }

                    var result = await responseHandler(response, token).ConfigureAwait(false);
                    return AttemptCycle<TResult>.Finish(result);
                }
            },
            (kind, _) => kind switch
            {
                AttemptFailureKind.Security => failureFactory("invalid_request", null),
                AttemptFailureKind.Timeout => failureFactory("timeout", null),
                _ => failureFactory("transient", null),
            },
            cancellationToken).ConfigureAwait(false);
    }

    /// <summary>判定連線或回應串流的暫時性例外是否可重試（文字、JSON 與下載路徑共用）</summary>
    internal static bool IsRetryableTransportException(Exception exception) => exception is HttpRequestException or IOException;

    /// <summary>執行通用 JSON 請求解析</summary>
    private Task<HttpJsonResponse<T>> ExecuteJsonRequestAsync<T>(
        Uri uri,
        Func<MemoryStream, CancellationToken, ValueTask<(bool Success, T? Value)>> parser,
        CancellationToken cancellationToken,
        Func<CancellationToken, Task<HttpResponseMessage>>? requestSender = null)
    {
        return ExecuteRequestWithRetryAsync(
            uri,
            async (response, token) =>
            {
                int statusCode = (int)response.StatusCode;
                if (response.StatusCode == HttpStatusCode.NotFound)
                {
                    return new HttpJsonResponse<T>(statusCode, default, "not_found");
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    return new HttpJsonResponse<T>(statusCode, default, "rate_limited");
                }

                if ((int)response.StatusCode >= 500)
                {
                    return new HttpJsonResponse<T>(statusCode, default, "transient");
                }

                if (!response.IsSuccessStatusCode)
                {
                    return new HttpJsonResponse<T>(statusCode, default, "invalid_request");
                }

                MemoryStream bodyStream;
                try
                {
                    bodyStream = await ReadLimitedMemoryStreamAsync(response, MaxJsonBytes, token).ConfigureAwait(false);
                }
                catch (HttpSecurityException exception)
                {
                    // 回應超過大小上限屬回應內容問題，不是請求本身無效
                    Logger.Warning(exception, "HTTP JSON 回應超過大小上限: {Uri}", uri);
                    return new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                }

                using (bodyStream)
                {
                    try
                    {
                        var (success, value) = await parser(bodyStream, token).ConfigureAwait(false);
                        return success && value is not null
                            ? new HttpJsonResponse<T>(statusCode, value, string.Empty)
                            : new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                    }
                    catch (JsonException exception)
                    {
                        Logger.Warning(exception, "HTTP JSON 回應格式無效: {Uri}", uri);
                        return new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                    }
                }
            },
            failureFactory: (error, status) => new HttpJsonResponse<T>(status, default, error),
            cancellationToken,
            requestSender);
    }

    private static async ValueTask<(bool Success, JsonDocument? Value)> ParseJsonDocumentAsync(MemoryStream stream, CancellationToken cancellationToken)
    {
        var doc = await JsonCodec.ParseDocumentAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
        return (doc is not null, doc);
    }

    public Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(
        Uri uri,
        CancellationToken cancellationToken = default) =>
        ExecuteJsonRequestAsync(uri, ParseJsonDocumentAsync, cancellationToken);

    public Task<string?> GetTextAsync(
        Uri uri,
        CancellationToken cancellationToken = default)
    {
        return ExecuteRequestWithRetryAsync(
            uri,
            async (response, token) =>
            {
                return response.IsSuccessStatusCode
                    ? await ReadLimitedUtf8Async(response, MaxTextBytes, token).ConfigureAwait(false)
                    : null;
            },
            failureFactory: (_, _) => null,
            cancellationToken);
    }

    public Task<HttpJsonResponse<JsonDocument>> PostJsonAsync(
        Uri uri,
        string jsonPayload,
        CancellationToken cancellationToken = default)
    {
        // 回應串流直接解析為 JsonDocument，不經中介字串
        return ExecuteJsonRequestAsync(
            uri,
            ParseJsonDocumentAsync,
            cancellationToken,
            requestSender: token =>
            {
                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                var request = new HttpRequestMessage(HttpMethod.Post, uri) { Content = content };
                EnsureUserAgent(request);
                return SendAndDisposeRequestAsync(request, token);
            });
    }

    private static async Task<string> ReadLimitedUtf8Async(
        HttpResponseMessage response,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        using var bodyStream = await ReadLimitedMemoryStreamAsync(response, maxBytes, cancellationToken).ConfigureAwait(false);
        return SafeFileSystem.DecodeUtf8WithoutBom(bodyStream.GetBuffer().AsSpan(0, (int)bodyStream.Length));
    }

    private static async Task<MemoryStream> ReadLimitedMemoryStreamAsync(
        HttpResponseMessage response,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        long? contentLength = response.Content.Headers.ContentLength;
        if (contentLength.HasValue && contentLength.Value > maxBytes)
        {
            throw new HttpSecurityException("HTTP 回應內容超過大小上限");
        }

        using var source = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        var memoryStream = new MemoryStream(contentLength.HasValue ? (int)Math.Min(contentLength.Value, 1024 * 1024) : 4096);
        byte[] buffer = ArrayPool<byte>.Shared.Rent(65536);
        try
        {
            long totalRead = 0L;
            int read;
            while ((read = await source.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false)) > 0)
            {
                totalRead += read;
                if (totalRead > maxBytes)
                {
                    throw new HttpSecurityException("HTTP 回應內容超過大小上限");
                }

                await memoryStream.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
            }

            memoryStream.Position = 0;
            return memoryStream;
        }
        catch (Exception)
        {
            await memoryStream.DisposeAsync().ConfigureAwait(false);
            throw;
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private async Task DelayBeforeRetryAsync(
        HttpResponseMessage response,
        TimeSpan baseRetryDelay,
        int attempt,
        CancellationToken cancellationToken)
    {
        var delay = ScaleDelay(baseRetryDelay, attempt);
        TimeSpan? retryAfter = response.Headers.RetryAfter switch
        {
            { Delta: { } delta } => delta,
            { Date: { } date } => date - _timeProvider.GetUtcNow(),
            _ => null,
        };
        if (retryAfter is { } requested)
        {
            delay = requested < TimeSpan.Zero ? TimeSpan.Zero : requested > MaxRetryDelay ? MaxRetryDelay : requested;
        }

        response.Dispose();
        await Task.Delay(delay, _timeProvider, cancellationToken).ConfigureAwait(false);
    }

    private static TimeSpan ScaleDelay(TimeSpan delay, int attempt) =>
        TimeSpan.FromMilliseconds(Math.Min(MaxRetryDelay.TotalMilliseconds, delay.TotalMilliseconds * Math.Max(1, attempt)));
}
