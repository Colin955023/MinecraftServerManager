using MinecraftServerManager.Infrastructure.Logging;
using System.Buffers;
using System.Collections.Frozen;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Http;

public sealed record HttpDownloadOptions
{
    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(60);

    public int MaxAttempts { get; init; } = 3;

    public int MaxRedirects { get; init; } = 10;

    public long MaxBytes { get; init; } = 512L * 1024 * 1024;

    public TimeSpan RetryDelay { get; init; } = TimeSpan.FromMilliseconds(100);

    public bool EnableRangeResumption { get; init; } = true;
}

public sealed record HttpDownloadProgress(long BytesDownloaded, long TotalBytes);

public sealed record HttpDownloadResult(bool Success, string? Error = null, long BytesDownloaded = 0);

public sealed record HttpRequestRetryOptions
{
    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(30);

    public int MaxAttempts { get; init; } = 3;

    public TimeSpan RetryDelay { get; init; } = TimeSpan.FromMilliseconds(100);

    public int MaxRedirects { get; init; } = 10;
}

public sealed class HttpDownloadClient : IHttpPort
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("HttpDownloadClient");
    public const long MaxJsonBytes = 16L * 1024 * 1024;
    public const long MaxTextBytes = 64L * 1024 * 1024;
    public const long DefaultMaxDownloadBytes = 512L * 1024 * 1024;
    public const int DefaultMaxRedirects = 10;
    public const int DefaultMaxAttempts = 3;

    private static readonly HttpStatusCode[] RetryableStatusesSource =
    [
        HttpStatusCode.RequestTimeout,
        HttpStatusCode.TooManyRequests,
        HttpStatusCode.InternalServerError,
        HttpStatusCode.BadGateway,
        HttpStatusCode.ServiceUnavailable,
        HttpStatusCode.GatewayTimeout,
    ];

    private static readonly FrozenSet<HttpStatusCode> RetryableStatuses = RetryableStatusesSource.ToFrozenSet();

    private readonly HttpClient _client;
    private readonly Func<string, CancellationToken, Task<IPAddress[]>>? _resolver;
    private readonly JsonSerializerOptions? _jsonCodecOptions;

    public HttpDownloadClient(
        HttpClient client,
        Func<string, CancellationToken, Task<IPAddress[]>>? resolver = null,
        JsonSerializerOptions? jsonSerializerOptions = null)
    {
        ArgumentNullException.ThrowIfNull(client);
        _client = client;
        _resolver = resolver;
        _jsonCodecOptions = jsonSerializerOptions;
    }

    /// <summary>
    /// IHttpPort 介面實作：安全下載檔案
    /// </summary>
    async Task<HttpResult> IHttpPort.DownloadAsync(
        Uri uri,
        string targetPath,
        IProgress<HttpProgress>? progress,
        string? expectedHash,
        string expectedHashAlgorithm,
        CancellationToken cancellationToken)
    {
        IProgress<HttpDownloadProgress>? downloadProgress = progress is null
            ? null
            : new ProgressBridge(progress);

        var result = await DownloadAsync(
            uri,
            targetPath,
            options: null,
            downloadProgress,
            expectedHash,
            expectedHashAlgorithm,
            cancellationToken).ConfigureAwait(false);

        return new HttpResult(result.Success, result.Error, result.BytesDownloaded);
    }

    /// <summary>
    /// 執行具備重試、重定向與逾時控制的 HTTP 請求
    /// </summary>
    private async Task<TResult> ExecuteRequestWithRetryAsync<TResult>(
        Uri uri,
        HttpRequestRetryOptions options,
        Func<HttpResponseMessage, CancellationToken, Task<(bool Handled, TResult Result)>> responseHandler,
        Func<string, int?, TResult> failureFactory,
        CancellationToken cancellationToken)
    {
        try
        {
            HttpUrlPolicy.ValidateStatic(uri);
        }
        catch (HttpSecurityException)
        {
            return failureFactory("invalid_request", null);
        }

        for (int attempt = 1; attempt <= options.MaxAttempts; attempt++)
        {
            using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            attemptCancellation.CancelAfter(options.Timeout);

            try
            {
                var response = await SendWithRedirectsAsync(uri, options.MaxRedirects, attemptCancellation.Token).ConfigureAwait(false);
                using (response)
                {
                    if (RetryableStatuses.Contains(response.StatusCode) && attempt < options.MaxAttempts)
                    {
                        await DelayBeforeRetryAsync(response, options.RetryDelay, attempt, cancellationToken).ConfigureAwait(false);
                        continue;
                    }

                    var (handled, result) = await responseHandler(response, attemptCancellation.Token).ConfigureAwait(false);
                    if (handled)
                    {
                        return result;
                    }
                }
            }
            catch (HttpSecurityException)
            {
                return failureFactory("invalid_request", null);
            }
            catch (HttpRequestException) when (attempt < options.MaxAttempts)
            {
                await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                return failureFactory("transient", null);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < options.MaxAttempts)
            {
                await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return failureFactory("timeout", null);
            }
            catch (IOException)
            {
                return failureFactory("transient", null);
            }
        }

        return failureFactory("transient", null);
    }

    /// <summary>
    /// 執行通用 JSON 請求解析
    /// </summary>
    private Task<HttpJsonResponse<T>> ExecuteJsonRequestAsync<T>(
        Uri uri,
        HttpRequestRetryOptions options,
        Func<MemoryStream, CancellationToken, ValueTask<(bool Success, T? Value)>> parser,
        CancellationToken cancellationToken)
    {
        return ExecuteRequestWithRetryAsync(
            uri,
            options,
            async (response, token) =>
            {
                int statusCode = (int)response.StatusCode;
                if (response.StatusCode == HttpStatusCode.NotFound)
                {
                    return (true, new HttpJsonResponse<T>(statusCode, default, "not_found"));
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    return (true, new HttpJsonResponse<T>(statusCode, default, "rate_limited"));
                }

                if ((int)response.StatusCode >= 500)
                {
                    return (true, new HttpJsonResponse<T>(statusCode, default, "transient"));
                }

                if (!response.IsSuccessStatusCode)
                {
                    return (true, new HttpJsonResponse<T>(statusCode, default, "invalid_request"));
                }

                long contentLength = response.Content.Headers.ContentLength ?? 0;
                if (contentLength > MaxJsonBytes)
                {
                    return (true, new HttpJsonResponse<T>(statusCode, default, "invalid_response"));
                }

                using var bodyStream = await ReadLimitedMemoryStreamAsync(response, MaxJsonBytes, token).ConfigureAwait(false);
                try
                {
                    var (success, value) = await parser(bodyStream, token).ConfigureAwait(false);
                    if (!success || value is null)
                    {
                        return (true, new HttpJsonResponse<T>(statusCode, default, "invalid_response"));
                    }

                    return (true, new HttpJsonResponse<T>(statusCode, value, string.Empty));
                }
                catch (JsonException)
                {
                    return (true, new HttpJsonResponse<T>(statusCode, default, "invalid_response"));
                }
            },
            failureFactory: (error, status) => new HttpJsonResponse<T>(status, default, error),
            cancellationToken);
    }

    /// <summary>
    /// IHttpPort 介面實作：安全取得 JSON 資料並反序列化
    /// </summary>
    public Task<HttpJsonResponse<T>> GetJsonAsync<T>(
        Uri uri,
        CancellationToken cancellationToken = default) =>
        GetJsonAsync<T>(uri, options: null, cancellationToken);

    /// <summary>
    /// 安全取得 JSON 資料並反序列化（支援自訂重試選項）
    /// </summary>
    public Task<HttpJsonResponse<T>> GetJsonAsync<T>(
        Uri uri,
        HttpRequestRetryOptions? options,
        CancellationToken cancellationToken = default)
    {
        var retryOptions = options ?? new HttpRequestRetryOptions { Timeout = TimeSpan.FromSeconds(10) };
        return ExecuteJsonRequestAsync(
            uri,
            retryOptions,
            (stream, _) =>
            {
                ReadOnlySpan<byte> utf8Span = stream.TryGetBuffer(out ArraySegment<byte> segment)
                    ? segment
                    : stream.ToArray();
                var payload = JsonCodec.Deserialize<T>(utf8Span, _jsonCodecOptions);
                return ValueTask.FromResult((payload is not null, payload));
            },
            cancellationToken);
    }

    /// <summary>
    /// IHttpPort 介面實作：安全取得 JSON 文件並以串流解析（呼叫端負責處置 JsonDocument）
    /// </summary>
    public Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(
        Uri uri,
        CancellationToken cancellationToken = default) =>
        GetJsonDocumentAsync(uri, options: null, cancellationToken);

    /// <summary>
    /// 安全取得 JSON 文件並以串流解析（支援自訂重試選項）
    /// </summary>
    public Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(
        Uri uri,
        HttpRequestRetryOptions? options,
        CancellationToken cancellationToken = default)
    {
        var retryOptions = options ?? new HttpRequestRetryOptions { Timeout = TimeSpan.FromSeconds(30) };
        return ExecuteJsonRequestAsync(
            uri,
            retryOptions,
            async (stream, token) =>
            {
                stream.Position = 0;
                var doc = await JsonCodec.ParseDocumentAsync(stream, cancellationToken: token).ConfigureAwait(false);
                return (doc is not null, doc);
            },
            cancellationToken);
    }

    /// <summary>
    /// IHttpPort 介面實作：安全取得文字內容
    /// </summary>
    public Task<string?> GetTextAsync(
        Uri uri,
        CancellationToken cancellationToken = default) =>
        GetTextAsync(uri, options: null, cancellationToken);

    /// <summary>
    /// 安全取得文字內容（支援自訂重試選項）
    /// </summary>
    public Task<string?> GetTextAsync(
        Uri uri,
        HttpRequestRetryOptions? options,
        CancellationToken cancellationToken = default)
    {
        var retryOptions = options ?? new HttpRequestRetryOptions { Timeout = TimeSpan.FromSeconds(30) };
        return ExecuteRequestWithRetryAsync<string?>(
            uri,
            retryOptions,
            async (response, token) =>
            {
                if (!response.IsSuccessStatusCode)
                {
                    return (true, null);
                }

                long contentLength = response.Content.Headers.ContentLength ?? 0;
                if (contentLength > MaxTextBytes)
                {
                    return (true, null);
                }

                using var bodyStream = await ReadLimitedMemoryStreamAsync(response, MaxTextBytes, token).ConfigureAwait(false);
                ReadOnlySpan<byte> utf8Span = bodyStream.TryGetBuffer(out ArraySegment<byte> segment)
                    ? segment
                    : bodyStream.ToArray();

                return (true, Encoding.UTF8.GetString(utf8Span));
            },
            failureFactory: (_, _) => null,
            cancellationToken);
    }
    /// <summary>
    /// IHttpPort 介面實作：安全傳送 POST JSON 請求並取得文字回應
    /// </summary>
    public async Task<string?> PostJsonAsync(
        Uri uri,
        string jsonPayload,
        CancellationToken cancellationToken = default)
    {
        try
        {
            HttpUrlPolicy.ValidateStatic(uri);
            if (_resolver is not null)
            {
                await HttpUrlPolicy.ValidatePublicHostAsync(uri, _resolver, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (HttpSecurityException)
        {
            return null;
        }

        try
        {
            using var content = new StringContent(jsonPayload ?? "{}", Encoding.UTF8, "application/json");
            using var request = new HttpRequestMessage(HttpMethod.Post, uri) { Content = content };
            EnsureUserAgent(request);
            var response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            using (response)
            {
                if (IsRedirect(response.StatusCode) || !response.IsSuccessStatusCode)
                {
                    return null;
                }

                long contentLength = response.Content.Headers.ContentLength ?? 0;
                if (contentLength > MaxJsonBytes)
                {
                    return null;
                }

                using var bodyStream = await ReadLimitedMemoryStreamAsync(response, MaxJsonBytes, cancellationToken).ConfigureAwait(false);
                ReadOnlySpan<byte> utf8Span = bodyStream.TryGetBuffer(out ArraySegment<byte> segment)
                    ? segment
                    : bodyStream.ToArray();

                return Encoding.UTF8.GetString(utf8Span);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            return null;
        }
    }

    public async Task<HttpDownloadResult> DownloadAsync(
        Uri uri,
        string targetPath,
        HttpDownloadOptions? options = null,
        IProgress<HttpDownloadProgress>? progress = null,
        string? expectedHash = null,
        string expectedHashAlgorithm = "sha256",
        CancellationToken cancellationToken = default)
    {
        options ??= new HttpDownloadOptions();
        ValidateOptions(options);
        HttpUrlPolicy.ValidateStatic(uri);
        string target = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
        string? normalizedHash = NormalizeExpectedHash(expectedHash, expectedHashAlgorithm);
        if (normalizedHash is not null && SafeFileSystem.FileExists(target))
        {
            string existing = HashCalculator.Shared.ComputeFileHash(target, expectedHashAlgorithm, maxBytes: options.MaxBytes);
            if (string.Equals(existing, normalizedHash, StringComparison.OrdinalIgnoreCase))
            {
                return new HttpDownloadResult(true, BytesDownloaded: SafeFileSystem.GetFileLength(target));
            }
        }

        string temporary = SafeFileSystem.ResolveStablePath(
            target + ".part",
            createParent: true);
        if (!options.EnableRangeResumption && SafeFileSystem.FileExists(temporary))
        {
            TryDeleteTemporaryFile(temporary);
        }

        try
        {
            Uri currentUri = uri;
            string? knownETag = null;
            for (int attempt = 1; attempt <= options.MaxAttempts; attempt++)
            {
                var (shouldRetry, finalResult, nextETag) = await TryDownloadAttemptAsync(
                    currentUri, temporary, target, options, normalizedHash, expectedHashAlgorithm, progress, attempt, knownETag, cancellationToken).ConfigureAwait(false);
                knownETag = nextETag;

                if (!shouldRetry)
                {
                    if (finalResult is not null && finalResult.Success)
                    {
                        temporary = string.Empty;
                    }

                    return finalResult ?? new HttpDownloadResult(false, "下載失敗");
                }
            }

            return new HttpDownloadResult(false, "下載重試次數已用盡");
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return new HttpDownloadResult(false, "下載已取消");
        }
        finally
        {
            if (!options.EnableRangeResumption || string.IsNullOrEmpty(temporary))
            {
                TryDeleteTemporaryFile(temporary);
            }
        }
    }

    private async Task<(bool ShouldRetry, HttpDownloadResult? FinalResult, string? KnownETag)> TryDownloadAttemptAsync(
        Uri currentUri,
        string temporary,
        string target,
        HttpDownloadOptions options,
        string? normalizedHash,
        string expectedHashAlgorithm,
        IProgress<HttpDownloadProgress>? progress,
        int attempt,
        string? knownETag,
        CancellationToken cancellationToken)
    {
        using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        attemptCancellation.CancelAfter(options.Timeout);

        long existingBytes = 0;
        if (options.EnableRangeResumption && SafeFileSystem.FileExists(temporary))
        {
            try
            {
                existingBytes = SafeFileSystem.GetFileLength(temporary);
                if (existingBytes >= options.MaxBytes)
                {
                    TryDeleteTemporaryFile(temporary);
                    existingBytes = 0;
                }
            }
            catch
            {
                existingBytes = 0;
            }
        }

        try
        {
            var response = await SendWithRedirectsAsync(
                currentUri,
                options,
                attemptCancellation.Token,
                fromByte: existingBytes > 0 ? existingBytes : null,
                ifRangeTag: existingBytes > 0 ? knownETag : null).ConfigureAwait(false);
            using (response)
            {
                string? responseETag = response.Headers.ETag?.Tag;

                if (response.StatusCode == HttpStatusCode.RequestedRangeNotSatisfiable)
                {
                    TryDeleteTemporaryFile(temporary);
                    if (attempt < options.MaxAttempts)
                    {
                        return (true, null, responseETag ?? knownETag);
                    }

                    return (false, new HttpDownloadResult(false, "HTTP 416 Range Not Satisfiable"), responseETag ?? knownETag);
                }

                if (RetryableStatuses.Contains(response.StatusCode) && attempt < options.MaxAttempts)
                {
                    await DelayBeforeRetryAsync(response, options, attempt, cancellationToken).ConfigureAwait(false);
                    return (true, null, responseETag ?? knownETag);
                }

                if (response.StatusCode is not HttpStatusCode.OK and not HttpStatusCode.PartialContent)
                {
                    TryDeleteTemporaryFile(temporary);
                    return (false, new HttpDownloadResult(false, $"HTTP 狀態碼： {(int)response.StatusCode}"), responseETag ?? knownETag);
                }

                bool isResume = response.StatusCode == HttpStatusCode.PartialContent && existingBytes > 0;
                if (isResume && knownETag is not null && responseETag is not null && !string.Equals(knownETag, responseETag, StringComparison.Ordinal))
                {
                    TryDeleteTemporaryFile(temporary);
                    if (attempt < options.MaxAttempts)
                    {
                        return (true, null, responseETag);
                    }

                    return (false, new HttpDownloadResult(false, "遠端檔案版本已變更"), responseETag);
                }

                long totalLength = isResume
                    ? (response.Content.Headers.ContentRange?.Length ?? (existingBytes + (response.Content.Headers.ContentLength ?? 0)))
                    : (response.Content.Headers.ContentLength ?? 0);

                if (totalLength > options.MaxBytes)
                {
                    TryDeleteTemporaryFile(temporary);
                    return (false, new HttpDownloadResult(false, "下載檔案超過大小上限"), responseETag ?? knownETag);
                }

                var result = await WriteResponseAsync(
                    response,
                    temporary,
                    options,
                    normalizedHash,
                    expectedHashAlgorithm,
                    progress,
                    attemptCancellation.Token,
                    isResume ? existingBytes : 0,
                    totalLength).ConfigureAwait(false);
                if (!result.Success)
                {
                    return (false, result, responseETag ?? knownETag);
                }

                if (!AtomicFileWriter.ReplaceFile(temporary, target))
                {
                    return (false, new HttpDownloadResult(false, "無法原子提交下載檔案"), responseETag ?? knownETag);
                }

                return (false, new HttpDownloadResult(true, BytesDownloaded: SafeFileSystem.GetFileLength(target)), responseETag ?? knownETag);
            }
        }
        catch (HttpSecurityException exception)
        {
            return (false, new HttpDownloadResult(false, exception.Message), knownETag);
        }
        catch (HttpRequestException exception) when (attempt < options.MaxAttempts)
        {
            await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            _ = exception;
            return (true, null, knownETag);
        }
        catch (HttpRequestException exception)
        {
            return (false, new HttpDownloadResult(false, exception.Message), knownETag);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < options.MaxAttempts)
        {
            await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            return (true, null, knownETag);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return (false, new HttpDownloadResult(false, "下載已取消"), knownETag);
        }
        catch (OperationCanceledException)
        {
            return (false, new HttpDownloadResult(false, "HTTP 請求逾時"), knownETag);
        }
        catch (IOException exception)
        {
            return (false, new HttpDownloadResult(false, exception.Message), knownETag);
        }
    }

    private Task<HttpResponseMessage> SendWithRedirectsAsync(
        Uri initialUri,
        HttpDownloadOptions options,
        CancellationToken cancellationToken,
        long? fromByte = null,
        string? ifRangeTag = null) =>
        SendWithRedirectsAsync(initialUri, options.MaxRedirects, cancellationToken, fromByte: fromByte, ifRangeTag: ifRangeTag);

    private async Task<HttpResponseMessage> SendWithRedirectsAsync(
        Uri initialUri,
        int maxRedirects,
        CancellationToken cancellationToken,
        HttpMethod? method = null,
        long? fromByte = null,
        long? toByte = null,
        string? ifRangeTag = null)
    {
        var currentUri = initialUri;
        method ??= HttpMethod.Get;
        for (int redirect = 0; ; redirect++)
        {
            if (_resolver is not null)
            {
                await HttpUrlPolicy.ValidatePublicHostAsync(currentUri, _resolver, cancellationToken).ConfigureAwait(false);
            }
            using var request = new HttpRequestMessage(method, currentUri);
            EnsureUserAgent(request);
            if (fromByte.HasValue && fromByte.Value >= 0)
            {
                request.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(fromByte.Value, toByte);
                if (!string.IsNullOrWhiteSpace(ifRangeTag))
                {
                    request.Headers.IfRange = new System.Net.Http.Headers.RangeConditionHeaderValue(ifRangeTag);
                }
            }
            var response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            if (!IsRedirect(response.StatusCode))
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
        catch
        {
            await memoryStream.DisposeAsync().ConfigureAwait(false);
            throw;
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static async Task<HttpDownloadResult> WriteResponseAsync(
        HttpResponseMessage response,
        string temporaryPath,
        HttpDownloadOptions options,
        string? expectedHash,
        string expectedHashAlgorithm,
        IProgress<HttpDownloadProgress>? progress,
        CancellationToken cancellationToken,
        long existingBytes = 0,
        long totalBytes = 0)
    {
        bool isResume = existingBytes > 0;
        using var source = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var output = new FileStream(
            temporaryPath,
            isResume ? FileMode.Append : FileMode.Create,
            FileAccess.Write,
            FileShare.None,
            81920,
            FileOptions.SequentialScan);
        using var hash = (!isResume && expectedHash is not null)
            ? IncrementalHash.CreateHash(CreateHashAlgorithmName(expectedHashAlgorithm))
            : null;

        byte[] buffer = ArrayPool<byte>.Shared.Rent(81920);
        try
        {
            long downloaded = existingBytes;
            long total = totalBytes > 0 ? totalBytes : (response.Content.Headers.ContentLength ?? 0);
            int read;
            while ((read = await source.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false)) > 0)
            {
                downloaded += read;
                if (downloaded > options.MaxBytes)
                {
                    return new HttpDownloadResult(false, "下載檔案超過大小上限", downloaded);
                }

                await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
                hash?.AppendData(buffer, 0, read);
                progress?.Report(new HttpDownloadProgress(downloaded, total));
            }

            await output.FlushAsync(cancellationToken).ConfigureAwait(false);
            output.Close();

            if (expectedHash is not null)
            {
                if (!isResume && hash is not null)
                {
                    byte[] actualBytes = hash.GetHashAndReset();
                    byte[] expectedBytes = Convert.FromHexString(expectedHash);
                    if (!CryptographicOperations.FixedTimeEquals(actualBytes, expectedBytes))
                    {
                        TryDeleteTemporaryFile(temporaryPath);
                        return new HttpDownloadResult(false, "下載檔案雜湊驗證失敗", downloaded);
                    }
                }
                else
                {
                    string computedHash = HashCalculator.Shared.ComputeFileHash(
                        temporaryPath,
                        expectedHashAlgorithm,
                        maxBytes: options.MaxBytes);
                    if (!string.Equals(computedHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                    {
                        TryDeleteTemporaryFile(temporaryPath);
                        return new HttpDownloadResult(false, "下載檔案雜湊驗證失敗", downloaded);
                    }
                }
            }

            return new HttpDownloadResult(true, BytesDownloaded: downloaded);
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static string? NormalizeExpectedHash(string? expectedHash, string algorithm)
    {
        if (string.IsNullOrWhiteSpace(expectedHash))
        {
            return null;
        }

        string normalized = expectedHash.Trim().ToLowerInvariant();
        int expectedLength = algorithm.Trim().ToLowerInvariant() switch
        {
            "sha1" => 40,
            "sha256" => 64,
            "sha512" => 128,
            _ => 0,
        };
        if (expectedLength == 0 || normalized.Length != expectedLength || normalized.Any(static character => !Uri.IsHexDigit(character)))
        {
            throw new ArgumentException("預期雜湊格式無效", nameof(expectedHash));
        }

        return normalized;
    }

    private static HashAlgorithmName CreateHashAlgorithmName(string algorithm) => algorithm.Trim().ToLowerInvariant() switch
    {
        "sha1" => HashAlgorithmName.SHA1,
        "sha256" => HashAlgorithmName.SHA256,
        "sha512" => HashAlgorithmName.SHA512,
        _ => throw new ArgumentException("不支援的雜湊演算法", nameof(algorithm)),
    };

    private static Task DelayBeforeRetryAsync(
        HttpResponseMessage response,
        HttpDownloadOptions options,
        int attempt,
        CancellationToken cancellationToken) =>
        DelayBeforeRetryAsync(response, options.RetryDelay, attempt, cancellationToken);

    private static async Task DelayBeforeRetryAsync(
        HttpResponseMessage response,
        TimeSpan baseRetryDelay,
        int attempt,
        CancellationToken cancellationToken)
    {
        var delay = ScaleDelay(baseRetryDelay, attempt);
        if (response.Headers.RetryAfter?.Delta is { } retryAfter)
        {
            delay = retryAfter <= TimeSpan.FromMinutes(1) ? retryAfter : TimeSpan.FromMinutes(1);
        }

        await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
    }

    private static TimeSpan ScaleDelay(TimeSpan delay, int attempt) =>
        TimeSpan.FromMilliseconds(Math.Min(TimeSpan.FromMinutes(1).TotalMilliseconds, delay.TotalMilliseconds * Math.Max(1, attempt)));

    private static bool IsRedirect(HttpStatusCode statusCode) => (int)statusCode is >= 300 and <= 399;

    private static void ValidateOptions(HttpDownloadOptions options)
    {
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(options.Timeout, TimeSpan.Zero);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.MaxAttempts, 1);
        ArgumentOutOfRangeException.ThrowIfNegative(options.MaxRedirects);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.MaxBytes, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.RetryDelay, TimeSpan.Zero, nameof(options));
    }

    private static void TryDeleteTemporaryFile(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return;
        }

        try
        {
            if (SafeFileSystem.FileExists(path))
            {
                SafeFileSystem.DeleteFile(path);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning("清理暫存下載檔失敗（已忽略）: {0}", ex.Message);
        }
    }

    private sealed class ProgressBridge(IProgress<HttpProgress> target) : IProgress<HttpDownloadProgress>
    {
        public void Report(HttpDownloadProgress value) =>
            target.Report(new HttpProgress(value.BytesDownloaded, value.TotalBytes));
    }
}
