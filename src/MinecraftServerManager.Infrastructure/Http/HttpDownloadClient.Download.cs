using System.Buffers;
using System.Net;
using System.Security.Cryptography;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Http;

public sealed partial class HttpDownloadClient
{
    public async Task<HttpResult> DownloadAsync(
        Uri uri,
        string targetPath,
        HttpDownloadOptions? options = null,
        IProgress<HttpProgress>? progress = null,
        string? expectedHash = null,
        string expectedHashAlgorithm = HashAlgorithmNames.Sha256,
        CancellationToken cancellationToken = default)
    {
        options ??= HttpDownloadOptions.Default;
        ValidateOptions(options);
        HttpUrlPolicy.ValidateStatic(uri);
        string target = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
        string? normalizedHash = NormalizeExpectedHash(expectedHash, expectedHashAlgorithm);
        if (normalizedHash is not null && SafeFileSystem.FileExists(target))
        {
            string existing = await HashCalculator.ComputeFileHashAsync(target, expectedHashAlgorithm, maxBytes: options.MaxBytes, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (string.Equals(existing, normalizedHash, StringComparison.OrdinalIgnoreCase))
            {
                return new HttpResult(true, BytesProcessed: SafeFileSystem.GetFileLength(target));
            }
        }

        string temporary = SafeFileSystem.ResolveStablePath(
            target + ".part",
            createParent: true);
        // 遺留的 .part 無 ETag 可比對，有預期雜湊時才沿用
        if ((!options.EnableRangeResumption || normalizedHash is null) && SafeFileSystem.FileExists(temporary))
        {
            SafeFileSystem.TryDeleteFile(temporary);
        }

        // 只有可續傳（啟用續傳且有預期雜湊）的失敗才保留 .part；取消時同樣保留供下次續傳
        bool keepPartial = options.EnableRangeResumption && normalizedHash is not null;
        string? knownETag = null;

        try
        {
            var result = await ExecuteAttemptLoopAsync(
                uri,
                options.MaxAttempts,
                options.Timeout,
                options.RetryDelay,
                "HTTP 下載",
                async (attempt, attemptTimeout, attemptToken) =>
                {
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
                            Logger.Warning(ex, "讀取續傳暫存檔長度失敗，改為重新下載");
                            existingBytes = 0;
                        }
                    }

                    // 無雜湊也無 ETag 時不續傳，避免拼接出不同版本的內容
                    if (existingBytes > 0 && normalizedHash is null && knownETag is null)
                    {
                        SafeFileSystem.TryDeleteFile(temporary);
                        existingBytes = 0;
                    }

                    var response = await SendWithRedirectsAsync(
                        uri,
                        options.MaxRedirects,
                        attemptToken,
                        fromByte: existingBytes > 0 ? existingBytes : null,
                        ifRangeTag: existingBytes > 0 ? knownETag : null).ConfigureAwait(false);
                    using (response)
                    {
                        string? responseETag = response.Headers.ETag is { IsWeak: false } etag ? etag.Tag : null;
                        knownETag = responseETag ?? knownETag;

                        if (response.StatusCode == HttpStatusCode.RequestedRangeNotSatisfiable)
                        {
                            SafeFileSystem.TryDeleteFile(temporary);
                            if (attempt < options.MaxAttempts)
                            {
                                return AttemptCycle<HttpResult>.Retry();
                            }

                            return AttemptCycle<HttpResult>.Finish(new HttpResult(false, "HTTP 416 Range Not Satisfiable"));
                        }

                        if (RetryableStatuses.Contains(response.StatusCode) && attempt < options.MaxAttempts)
                        {
                            await DelayBeforeRetryAsync(response, options.RetryDelay, attempt, cancellationToken).ConfigureAwait(false);
                            return AttemptCycle<HttpResult>.Retry();
                        }

                        if (response.StatusCode is not HttpStatusCode.OK and not HttpStatusCode.PartialContent)
                        {
                            SafeFileSystem.TryDeleteFile(temporary);
                            return AttemptCycle<HttpResult>.Finish(new HttpResult(false, $"HTTP 狀態碼： {(int)response.StatusCode}"));
                        }

                        if (response.StatusCode == HttpStatusCode.PartialContent &&
                            (existingBytes == 0 || response.Content.Headers.ContentRange?.From != existingBytes))
                        {
                            SafeFileSystem.TryDeleteFile(temporary);
                            if (attempt < options.MaxAttempts)
                            {
                                return AttemptCycle<HttpResult>.Retry();
                            }

                            return AttemptCycle<HttpResult>.Finish(new HttpResult(false, "續傳區段與已下載內容不符"));
                        }

                        bool isResume = response.StatusCode == HttpStatusCode.PartialContent;
                        if (isResume && knownETag is not null && responseETag is not null && !string.Equals(knownETag, responseETag, StringComparison.Ordinal))
                        {
                            SafeFileSystem.TryDeleteFile(temporary);
                            if (attempt < options.MaxAttempts)
                            {
                                return AttemptCycle<HttpResult>.Retry();
                            }

                            return AttemptCycle<HttpResult>.Finish(new HttpResult(false, "遠端檔案版本已變更"));
                        }

                        long totalLength = isResume
                            ? (response.Content.Headers.ContentRange?.Length ?? (existingBytes + (response.Content.Headers.ContentLength ?? 0)))
                            : (response.Content.Headers.ContentLength ?? 0);

                        if (totalLength > options.MaxBytes)
                        {
                            SafeFileSystem.TryDeleteFile(temporary);
                            return AttemptCycle<HttpResult>.Finish(new HttpResult(false, "下載檔案超過大小上限"));
                        }

                        var (writeResult, hashMismatch) = await WriteResponseAsync(
                            response,
                            temporary,
                            options,
                            normalizedHash,
                            expectedHashAlgorithm,
                            progress,
                            _timeProvider,
                            attemptToken,
                            isResume ? existingBytes : 0,
                            totalLength,
                            onDataReceived: () => attemptTimeout.CancelAfter(options.Timeout)).ConfigureAwait(false);

                        if (!writeResult.Success)
                        {
                            if (hashMismatch && isResume && attempt < options.MaxAttempts)
                            {
                                Logger.Warning("續傳下載雜湊不符，改為完整重新下載: {Uri}", uri);
                                knownETag = null;
                                return AttemptCycle<HttpResult>.Retry();
                            }

                            return AttemptCycle<HttpResult>.Finish(writeResult);
                        }

                        if (!AtomicFileWriter.ReplaceFile(temporary, target))
                        {
                            return AttemptCycle<HttpResult>.Finish(new HttpResult(false, "無法原子提交下載檔案"));
                        }

                        return AttemptCycle<HttpResult>.Finish(new HttpResult(true, BytesProcessed: SafeFileSystem.GetFileLength(target)));
                    }
                },
                (kind, msg) => new HttpResult(false, kind switch
                {
                    AttemptFailureKind.Timeout => "HTTP 請求逾時",
                    AttemptFailureKind.Exhausted => "下載重試次數已用盡",
                    _ => msg,
                }),
                cancellationToken).ConfigureAwait(false);

            if (result.Success)
            {
                SafeFileSystem.TryDeleteFile(temporary);
            }

            return result;
        }
        finally
        {
            if (!keepPartial)
            {
                SafeFileSystem.TryDeleteFile(temporary);
            }
        }
    }

    private static async Task<(HttpResult Result, bool HashMismatch)> WriteResponseAsync(
        HttpResponseMessage response,
        string temporaryPath,
        HttpDownloadOptions options,
        string? expectedHash,
        string expectedHashAlgorithm,
        IProgress<HttpProgress>? progress,
        TimeProvider timeProvider,
        CancellationToken cancellationToken,
        long existingBytes = 0,
        long totalBytes = 0,
        Action? onDataReceived = null)
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
            long reportedBytes = downloaded;
            var progressThrottle = new ProgressThrottle(ProgressReportInterval, timeProvider);
            int read;
            while ((read = await source.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false)) > 0)
            {
                onDataReceived?.Invoke();
                downloaded += read;
                if (downloaded > options.MaxBytes)
                {
                    await output.DisposeAsync().ConfigureAwait(false);
                    SafeFileSystem.TryDeleteFile(temporaryPath);
                    return (new HttpResult(false, "下載檔案超過大小上限", downloaded), false);
                }

                await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
                hash?.AppendData(buffer, 0, read);

                // 進度回報節流：最多每 100 毫秒一次，迴圈結束後補報最後一筆
                if (progress is not null && progressThrottle.ShouldReport())
                {
                    progress.Report(new HttpProgress(downloaded, total));
                    reportedBytes = downloaded;
                }
            }

            if (progress is not null && reportedBytes != downloaded)
            {
                progress.Report(new HttpProgress(downloaded, total));
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
                        return (new HttpResult(false, "下載檔案雜湊驗證失敗", downloaded), true);
                    }
                }
                else
                {
                    string computedHash = await HashCalculator.ComputeFileHashAsync(
                        temporaryPath,
                        expectedHashAlgorithm,
                        maxBytes: options.MaxBytes,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                    if (!string.Equals(computedHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                    {
                        SafeFileSystem.TryDeleteFile(temporaryPath);
                        return (new HttpResult(false, "下載檔案雜湊驗證失敗", downloaded), true);
                    }
                }
            }

            return (new HttpResult(true, BytesProcessed: downloaded), false);
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

    private static void ValidateOptions(HttpDownloadOptions options)
    {
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(options.Timeout, TimeSpan.Zero);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.MaxAttempts, 1);
        ArgumentOutOfRangeException.ThrowIfNegative(options.MaxRedirects);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.MaxBytes, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.RetryDelay, TimeSpan.Zero, nameof(options));
    }
}
