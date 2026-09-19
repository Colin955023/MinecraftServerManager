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
}

public sealed record HttpDownloadProgress(long BytesDownloaded, long TotalBytes);

public sealed record HttpDownloadResult(bool Success, string? Error = null, long BytesDownloaded = 0);

public sealed class HttpDownloadClient : IHttpPort
{
    public const long MaxJsonBytes = 16L * 1024 * 1024;
    public const long MaxTextBytes = 64L * 1024 * 1024;
    public const long DefaultMaxDownloadBytes = 512L * 1024 * 1024;
    public const int DefaultMaxRedirects = 10;
    public const int DefaultMaxAttempts = 3;

    private static readonly FrozenSet<HttpStatusCode> RetryableStatuses = new[]
    {
        HttpStatusCode.RequestTimeout,
        HttpStatusCode.TooManyRequests,
        HttpStatusCode.InternalServerError,
        HttpStatusCode.BadGateway,
        HttpStatusCode.ServiceUnavailable,
        HttpStatusCode.GatewayTimeout,
    }.ToFrozenSet();

    private static readonly JsonSerializerOptions JsonCodecOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly Func<string, CancellationToken, Task<IPAddress[]>>? _resolver;

    public HttpDownloadClient(
        HttpClient client,
        Func<string, CancellationToken, Task<IPAddress[]>>? resolver = null)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _resolver = resolver;
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
    /// IHttpPort 介面實作：安全取得 JSON 資料並反序列化
    /// </summary>
    public async Task<HttpJsonResponse<T>> GetJsonAsync<T>(
        Uri uri,
        CancellationToken cancellationToken = default)
    {
        try
        {
            HttpUrlPolicy.ValidateStatic(uri);
        }
        catch (HttpSecurityException)
        {
            return new HttpJsonResponse<T>(null, default, "invalid_request");
        }

        const int maxAttempts = DefaultMaxAttempts;
        var timeout = TimeSpan.FromSeconds(10);
        var retryDelay = TimeSpan.FromMilliseconds(100);

        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            attemptCancellation.CancelAfter(timeout);

            try
            {
                var response = await SendWithRedirectsAsync(uri, DefaultMaxRedirects, attemptCancellation.Token).ConfigureAwait(false);
                using (response)
                {
                    if (RetryableStatuses.Contains(response.StatusCode) && attempt < maxAttempts)
                    {
                        await DelayBeforeRetryAsync(response, retryDelay, attempt, cancellationToken).ConfigureAwait(false);
                        continue;
                    }

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

                    if (response.Content.Headers.ContentEncoding.Any(static encoding =>
                            !string.Equals(encoding, "identity", StringComparison.OrdinalIgnoreCase)))
                    {
                        return new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                    }

                    long contentLength = response.Content.Headers.ContentLength ?? 0;
                    if (contentLength > MaxJsonBytes)
                    {
                        return new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                    }

                    using var bodyStream = await ReadLimitedMemoryStreamAsync(response, MaxJsonBytes, attemptCancellation.Token).ConfigureAwait(false);
                    try
                    {
                        ReadOnlySpan<byte> utf8Span = bodyStream.TryGetBuffer(out ArraySegment<byte> segment)
                            ? segment.AsSpan()
                            : bodyStream.ToArray();

                        var payload = JsonSerializer.Deserialize<T>(utf8Span, JsonCodecOptions);
                        if (payload is null)
                        {
                            return new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                        }

                        return new HttpJsonResponse<T>(statusCode, payload, string.Empty);
                    }
                    catch (JsonException)
                    {
                        return new HttpJsonResponse<T>(statusCode, default, "invalid_response");
                    }
                }
            }
            catch (HttpSecurityException)
            {
                return new HttpJsonResponse<T>(null, default, "invalid_request");
            }
            catch (HttpRequestException) when (attempt < maxAttempts)
            {
                await Task.Delay(ScaleDelay(retryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                return new HttpJsonResponse<T>(null, default, "transient");
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < maxAttempts)
            {
                await Task.Delay(ScaleDelay(retryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                return new HttpJsonResponse<T>(null, default, "timeout");
            }
            catch (OperationCanceledException)
            {
                return new HttpJsonResponse<T>(null, default, "timeout");
            }
            catch (IOException)
            {
                return new HttpJsonResponse<T>(null, default, "transient");
            }
        }

        return new HttpJsonResponse<T>(null, default, "transient");
    }

    /// <summary>
    /// IHttpPort 介面實作：安全取得文字內容
    /// </summary>
    public async Task<string?> GetTextAsync(
        Uri uri,
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

        const int maxAttempts = DefaultMaxAttempts;
        var timeout = TimeSpan.FromSeconds(30);
        var retryDelay = TimeSpan.FromMilliseconds(100);

        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            attemptCancellation.CancelAfter(timeout);

            try
            {
                var response = await SendWithRedirectsAsync(uri, DefaultMaxRedirects, attemptCancellation.Token).ConfigureAwait(false);
                using (response)
                {
                    if (RetryableStatuses.Contains(response.StatusCode) && attempt < maxAttempts)
                    {
                        await DelayBeforeRetryAsync(response, retryDelay, attempt, cancellationToken).ConfigureAwait(false);
                        continue;
                    }

                    if (!response.IsSuccessStatusCode)
                    {
                        return null;
                    }

                    if (response.Content.Headers.ContentEncoding.Any(static encoding =>
                            !string.Equals(encoding, "identity", StringComparison.OrdinalIgnoreCase)))
                    {
                        return null;
                    }

                    long contentLength = response.Content.Headers.ContentLength ?? 0;
                    if (contentLength > MaxTextBytes)
                    {
                        return null;
                    }

                    using var bodyStream = await ReadLimitedMemoryStreamAsync(response, MaxTextBytes, attemptCancellation.Token).ConfigureAwait(false);
                    ReadOnlySpan<byte> utf8Span = bodyStream.TryGetBuffer(out ArraySegment<byte> segment)
                        ? segment.AsSpan()
                        : bodyStream.ToArray();

                    return Encoding.UTF8.GetString(utf8Span);
                }
            }
            catch (HttpSecurityException)
            {
                return null;
            }
            catch (HttpRequestException) when (attempt < maxAttempts)
            {
                await Task.Delay(ScaleDelay(retryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                return null;
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < maxAttempts)
            {
                await Task.Delay(ScaleDelay(retryDelay, attempt), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return null;
            }
            catch (IOException)
            {
                return null;
            }
        }

        return null;
    }

    /// <summary>
    /// IHttpPort 介面實作：安全發送 POST JSON 請求並取得文字回應
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
            var response = await _client.SendAsync(request, HttpCompletionOption.ResponseContentRead, cancellationToken).ConfigureAwait(false);
            using (response)
            {
                if (!response.IsSuccessStatusCode)
                {
                    return null;
                }

                return await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            }
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
        if (normalizedHash is not null && File.Exists(target))
        {
            string existing = HashCalculator.Shared.ComputeFileHash(target, expectedHashAlgorithm, maxBytes: options.MaxBytes);
            if (string.Equals(existing, normalizedHash, StringComparison.OrdinalIgnoreCase))
            {
                return new HttpDownloadResult(true, BytesDownloaded: new FileInfo(target).Length);
            }
        }

        string temporary = SafeFileSystem.ResolveStablePath(
            target + "." + Guid.NewGuid().ToString("N") + ".part",
            createParent: true);
        try
        {
            Uri currentUri = uri;
            for (int attempt = 1; attempt <= options.MaxAttempts; attempt++)
            {
                var (shouldRetry, finalResult) = await TryDownloadAttemptAsync(
                    currentUri, temporary, target, options, normalizedHash, expectedHashAlgorithm, progress, attempt, cancellationToken).ConfigureAwait(false);

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
            TryDeleteTemporaryFile(temporary);
        }
    }

    private async Task<(bool ShouldRetry, HttpDownloadResult? FinalResult)> TryDownloadAttemptAsync(
        Uri currentUri,
        string temporary,
        string target,
        HttpDownloadOptions options,
        string? normalizedHash,
        string expectedHashAlgorithm,
        IProgress<HttpDownloadProgress>? progress,
        int attempt,
        CancellationToken cancellationToken)
    {
        using var attemptCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        attemptCancellation.CancelAfter(options.Timeout);

        try
        {
            var response = await SendWithRedirectsAsync(currentUri, options, attemptCancellation.Token).ConfigureAwait(false);
            using (response)
            {
                if (RetryableStatuses.Contains(response.StatusCode) && attempt < options.MaxAttempts)
                {
                    await DelayBeforeRetryAsync(response, options, attempt, cancellationToken).ConfigureAwait(false);
                    return (true, null);
                }

                if (!response.IsSuccessStatusCode)
                {
                    return (false, new HttpDownloadResult(false, $"HTTP 狀態碼： {(int)response.StatusCode}"));
                }

                if (response.Content.Headers.ContentEncoding.Any(static encoding =>
                        !string.Equals(encoding, "identity", StringComparison.OrdinalIgnoreCase)))
                {
                    return (false, new HttpDownloadResult(false, "不支援壓縮 HTTP response"));
                }

                long contentLength = response.Content.Headers.ContentLength ?? 0;
                if (contentLength > options.MaxBytes)
                {
                    return (false, new HttpDownloadResult(false, "下載檔案超過大小上限"));
                }

                var result = await WriteResponseAsync(
                    response,
                    temporary,
                    options,
                    normalizedHash,
                    expectedHashAlgorithm,
                    progress,
                    attemptCancellation.Token).ConfigureAwait(false);
                if (!result.Success)
                {
                    return (false, result);
                }

                if (!AtomicFileWriter.ReplaceFile(temporary, target))
                {
                    return (false, new HttpDownloadResult(false, "無法原子提交下載檔案"));
                }

                return (false, new HttpDownloadResult(true, BytesDownloaded: new FileInfo(target).Length));
            }
        }
        catch (HttpSecurityException exception)
        {
            return (false, new HttpDownloadResult(false, exception.Message));
        }
        catch (HttpRequestException exception) when (attempt < options.MaxAttempts)
        {
            await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            _ = exception;
            return (true, null);
        }
        catch (HttpRequestException exception)
        {
            return (false, new HttpDownloadResult(false, exception.Message));
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && attempt < options.MaxAttempts)
        {
            await Task.Delay(ScaleDelay(options.RetryDelay, attempt), cancellationToken).ConfigureAwait(false);
            return (true, null);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return (false, new HttpDownloadResult(false, "下載已取消"));
        }
        catch (OperationCanceledException)
        {
            return (false, new HttpDownloadResult(false, "HTTP 請求逾時"));
        }
        catch (IOException exception)
        {
            return (false, new HttpDownloadResult(false, exception.Message));
        }
    }

    private Task<HttpResponseMessage> SendWithRedirectsAsync(
        Uri initialUri,
        HttpDownloadOptions options,
        CancellationToken cancellationToken) =>
        SendWithRedirectsAsync(initialUri, options.MaxRedirects, cancellationToken);

    private async Task<HttpResponseMessage> SendWithRedirectsAsync(
        Uri initialUri,
        int maxRedirects,
        CancellationToken cancellationToken)
    {
        var currentUri = initialUri;
        for (int redirect = 0; ; redirect++)
        {
            await HttpUrlPolicy.ValidatePublicHostAsync(currentUri, _resolver, cancellationToken).ConfigureAwait(false);
            using var request = new HttpRequestMessage(HttpMethod.Get, currentUri);
            EnsureUserAgent(request);
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
        byte[] buffer = System.Buffers.ArrayPool<byte>.Shared.Rent(65536);
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
            System.Buffers.ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static async Task<HttpDownloadResult> WriteResponseAsync(
        HttpResponseMessage response,
        string temporaryPath,
        HttpDownloadOptions options,
        string? expectedHash,
        string expectedHashAlgorithm,
        IProgress<HttpDownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        using var source = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var output = new FileStream(temporaryPath, FileMode.Create, FileAccess.Write, FileShare.None, 1024 * 1024, FileOptions.WriteThrough);
        using var hash = expectedHash is null ? null : IncrementalHash.CreateHash(CreateHashAlgorithmName(expectedHashAlgorithm));
        byte[] buffer = System.Buffers.ArrayPool<byte>.Shared.Rent(1024 * 1024);
        try
        {
            long downloaded = 0L;
            long total = response.Content.Headers.ContentLength ?? 0;
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
            if (expectedHash is not null)
            {
                string actual = Convert.ToHexString(hash!.GetHashAndReset()).ToLowerInvariant();
                if (!CryptographicOperations.FixedTimeEquals(Convert.FromHexString(actual), Convert.FromHexString(expectedHash)))
                {
                    return new HttpDownloadResult(false, "下載檔案雜湊驗證失敗", downloaded);
                }
            }

            return new HttpDownloadResult(true, BytesDownloaded: downloaded);
        }
        finally
        {
            System.Buffers.ArrayPool<byte>.Shared.Return(buffer);
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
        if (options.RetryDelay < TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(options));
        }
    }

    private static void TryDeleteTemporaryFile(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return;
        }

        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private sealed class ProgressBridge(IProgress<HttpProgress> target) : IProgress<HttpDownloadProgress>
    {
        public void Report(HttpDownloadProgress value) =>
            target.Report(new HttpProgress(value.BytesDownloaded, value.TotalBytes));
    }
}
