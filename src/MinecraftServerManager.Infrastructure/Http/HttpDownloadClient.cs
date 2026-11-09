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

public sealed class HttpDownloadClient : IHttpPort
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(HttpDownloadClient));
    public const long MaxJsonBytes = 16L * 1024 * 1024;
    public const long MaxTextBytes = 64L * 1024 * 1024;

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
    private const int RequestMaxAttempts = 3;
    private const int RequestMaxRedirects = 10;
    private static readonly TimeSpan RequestRetryDelay = TimeSpan.FromMilliseconds(100);
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(30);

    public HttpDownloadClient(HttpClient client)
    {
        ArgumentNullException.ThrowIfNull(client);
        _client = client;
    }

    /// <summary>
    /// IHttpPort 介面實作：安全下載檔案（使用預設下載選項）
    /// </summary>
    Task<HttpResult> IHttpPort.DownloadAsync(
        Uri uri,
        string targetPath,
        IProgress<HttpProgress>? progress,
        string? expectedHash,
        string expectedHashAlgorithm,
        CancellationToken cancellationToken) =>
        DownloadAsync(uri, targetPath, options: null, progress, expectedHash, expectedHashAlgorithm, cancellationToken);

    /// <summary>
    /// 執行具備重試、重定向與逾時控制的 HTTP 請求
    /// </summary>
    private async Task<TResult> ExecuteRequestWithRetryAsync<TResult>(
        Uri uri,
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

        for (int attempt = 1; attempt <= RequestMaxAttempts; attempt++)
        {
            using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            attemptCancellation.CancelAfter(RequestTimeout);

            try
            {
                var response = await SendWithRedirectsAsync(uri, RequestMaxRedirects, attemptCancellation.Token).ConfigureAwait(false);
                using (response)
                {
                    if (RetryableStatuses.Contains(response.StatusCode) && attempt < RequestMaxAttempts)
                    {
                        await DelayBeforeRetryAsync(response, RequestRetryDelay, attempt, cancellationToken).ConfigureAwait(false);
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
            catch (HttpRequestException) when (attempt < RequestMaxAttempts)
            {
                await Task.Delay(ScaleDelay(RequestRetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                return failureFactory("transient", null);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < RequestMaxAttempts)
            {
                await Task.Delay(ScaleDelay(RequestRetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    throw;
                }
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
        Func<MemoryStream, CancellationToken, ValueTask<(bool Success, T? Value)>> parser,
        CancellationToken cancellationToken)
    {
        return ExecuteRequestWithRetryAsync(
            uri,
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
    /// IHttpPort 介面實作：安全取得 JSON 文件並以串流解析（呼叫端負責處置 JsonDocument）
    /// </summary>
    public Task<HttpJsonResponse<JsonDocument>> GetJsonDocumentAsync(
        Uri uri,
        CancellationToken cancellationToken = default)
    {
        return ExecuteJsonRequestAsync(
            uri,
            async (stream, token) =>
            {
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
        CancellationToken cancellationToken = default)
    {
        return ExecuteRequestWithRetryAsync<string?>(
            uri,
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

                return (true, await ReadLimitedUtf8Async(response, MaxTextBytes, token).ConfigureAwait(false));
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

                return await ReadLimitedUtf8Async(response, MaxJsonBytes, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("POST JSON 請求失敗: {0}", ex.Message);
            return null;
        }
    }

    public async Task<HttpResult> DownloadAsync(
        Uri uri,
        string targetPath,
        HttpDownloadOptions? options = null,
        IProgress<HttpProgress>? progress = null,
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
            string existing = await HashCalculator.Shared.ComputeFileHashAsync(target, expectedHashAlgorithm, useCache: false, maxBytes: options.MaxBytes, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (string.Equals(existing, normalizedHash, StringComparison.OrdinalIgnoreCase))
            {
                return new HttpResult(true, BytesProcessed: SafeFileSystem.GetFileLength(target));
            }
        }

        string temporary = SafeFileSystem.ResolveStablePath(
            target + ".part",
            createParent: true);
        // 前次呼叫遺留之 .part 無 ETag 可比對，僅在有預期雜湊可驗證最終結果時才沿用
        if ((!options.EnableRangeResumption || normalizedHash is null) && SafeFileSystem.FileExists(temporary))
        {
            SafeFileSystem.TryDeleteFile(temporary);
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

                    return finalResult ?? new HttpResult(false, "下載失敗");
                }
            }

            return new HttpResult(false, "下載重試次數已用盡");
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return new HttpResult(false, "下載已取消");
        }
        finally
        {
            if (!options.EnableRangeResumption || string.IsNullOrEmpty(temporary))
            {
                SafeFileSystem.TryDeleteFile(temporary);
            }
        }
    }

    private async Task<(bool ShouldRetry, HttpResult? FinalResult, string? KnownETag)> TryDownloadAttemptAsync(
        Uri currentUri,
        string temporary,
        string target,
        HttpDownloadOptions options,
        string? normalizedHash,
        string expectedHashAlgorithm,
        IProgress<HttpProgress>? progress,
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
                    SafeFileSystem.TryDeleteFile(temporary);
                    existingBytes = 0;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning("讀取續傳暫存檔長度失敗，改為重新下載: {0}", ex.Message);
                existingBytes = 0;
            }
        }

        try
        {
            var response = await SendWithRedirectsAsync(
                currentUri,
                options.MaxRedirects,
                attemptCancellation.Token,
                fromByte: existingBytes > 0 ? existingBytes : null,
                ifRangeTag: existingBytes > 0 ? knownETag : null).ConfigureAwait(false);
            using (response)
            {
                string? responseETag = response.Headers.ETag?.Tag;

                if (response.StatusCode == HttpStatusCode.RequestedRangeNotSatisfiable)
                {
                    SafeFileSystem.TryDeleteFile(temporary);
                    if (attempt < options.MaxAttempts)
                    {
                        return (true, null, responseETag ?? knownETag);
                    }

                    return (false, new HttpResult(false, "HTTP 416 Range Not Satisfiable"), responseETag ?? knownETag);
                }

                if (RetryableStatuses.Contains(response.StatusCode) && attempt < options.MaxAttempts)
                {
                    await DelayBeforeRetryAsync(response, options.RetryDelay, attempt, cancellationToken).ConfigureAwait(false);
                    return (true, null, responseETag ?? knownETag);
                }

                if (response.StatusCode is not HttpStatusCode.OK and not HttpStatusCode.PartialContent)
                {
                    SafeFileSystem.TryDeleteFile(temporary);
                    return (false, new HttpResult(false, $"HTTP 狀態碼： {(int)response.StatusCode}"), responseETag ?? knownETag);
                }

                bool isResume = response.StatusCode == HttpStatusCode.PartialContent && existingBytes > 0;
                if (isResume && knownETag is not null && responseETag is not null && !string.Equals(knownETag, responseETag, StringComparison.Ordinal))
                {
                    SafeFileSystem.TryDeleteFile(temporary);
                    if (attempt < options.MaxAttempts)
                    {
                        return (true, null, responseETag);
                    }

                    return (false, new HttpResult(false, "遠端檔案版本已變更"), responseETag);
                }

                long totalLength = isResume
                    ? (response.Content.Headers.ContentRange?.Length ?? (existingBytes + (response.Content.Headers.ContentLength ?? 0)))
                    : (response.Content.Headers.ContentLength ?? 0);

                if (totalLength > options.MaxBytes)
                {
                    SafeFileSystem.TryDeleteFile(temporary);
                    return (false, new HttpResult(false, "下載檔案超過大小上限"), responseETag ?? knownETag);
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
                    return (false, new HttpResult(false, "無法原子提交下載檔案"), responseETag ?? knownETag);
                }

                return (false, new HttpResult(true, BytesProcessed: SafeFileSystem.GetFileLength(target)), responseETag ?? knownETag);
            }
        }
        catch (HttpSecurityException exception)
        {
            return (false, new HttpResult(false, exception.Message), knownETag);
        }
        catch (HttpRequestException exception) when (attempt < options.MaxAttempts)
        {
            await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            Logger.Warning("HTTP 下載要求失敗，準備進行第 {0} 次重試: {1}", attempt, exception.Message);
            return (true, null, knownETag);
        }
        catch (HttpRequestException exception)
        {
            return (false, new HttpResult(false, exception.Message), knownETag);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < options.MaxAttempts)
        {
            await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            return (true, null, knownETag);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return (false, new HttpResult(false, "下載已取消"), knownETag);
        }
        catch (OperationCanceledException)
        {
            return (false, new HttpResult(false, "HTTP 請求逾時"), knownETag);
        }
        catch (IOException exception)
        {
            return (false, new HttpResult(false, exception.Message), knownETag);
        }
    }

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

    private static async Task<string> ReadLimitedUtf8Async(
        HttpResponseMessage response,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        using var bodyStream = await ReadLimitedMemoryStreamAsync(response, maxBytes, cancellationToken).ConfigureAwait(false);
        return Encoding.UTF8.GetString(bodyStream.GetBuffer().AsSpan(0, (int)bodyStream.Length));
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

    private static async Task<HttpResult> WriteResponseAsync(
        HttpResponseMessage response,
        string temporaryPath,
        HttpDownloadOptions options,
        string? expectedHash,
        string expectedHashAlgorithm,
        IProgress<HttpProgress>? progress,
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
            bufferSize: 0, // 已自備 ArrayPool 緩衝區，停用 FileStream 內部緩衝避免重複配置
            FileOptions.Asynchronous | FileOptions.SequentialScan);
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
                    return new HttpResult(false, "下載檔案超過大小上限", downloaded);
                }

                await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
                hash?.AppendData(buffer, 0, read);
                progress?.Report(new HttpProgress(downloaded, total));
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
                        SafeFileSystem.TryDeleteFile(temporaryPath);
                        return new HttpResult(false, "下載檔案雜湊驗證失敗", downloaded);
                    }
                }
                else
                {
                    string computedHash = await HashCalculator.Shared.ComputeFileHashAsync(
                        temporaryPath,
                        expectedHashAlgorithm,
                        useCache: false,
                        maxBytes: options.MaxBytes,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                    if (!string.Equals(computedHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                    {
                        SafeFileSystem.TryDeleteFile(temporaryPath);
                        return new HttpResult(false, "下載檔案雜湊驗證失敗", downloaded);
                    }
                }
            }

            return new HttpResult(true, BytesProcessed: downloaded);
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
        if (!HashCalculator.TryResolveAlgorithm(algorithm, out _, out int expectedLength) || !HashCalculator.IsHexDigest(normalized, expectedLength))
        {
            throw new ArgumentException("預期雜湊格式無效", nameof(expectedHash));
        }

        return normalized;
    }

    private static HashAlgorithmName CreateHashAlgorithmName(string algorithm) =>
        HashCalculator.TryResolveAlgorithm(algorithm, out var name, out _)
            ? name
            : throw new ArgumentException("不支援的雜湊演算法", nameof(algorithm));

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
}
