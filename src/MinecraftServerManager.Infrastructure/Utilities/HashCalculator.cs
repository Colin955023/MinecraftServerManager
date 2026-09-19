using System.Collections.Concurrent;
using System.Diagnostics.CodeAnalysis;
using System.Security.Cryptography;

namespace MinecraftServerManager.Infrastructure.Utilities;

public sealed class HashCalculator
{
    public const long DefaultMaxBytes = 512L * 1024 * 1024;

    private const int MaxCacheEntries = 1024;
    private static readonly HashCalculator SharedInstance = new();
    private readonly ConcurrentDictionary<CacheKey, string> cache = new();

    public static HashCalculator Shared => SharedInstance;

    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有模組雜湊比對相容性，不作為密碼用途")]
    public static string DigestBytes(ReadOnlySpan<byte> content, string algorithm = "sha256") =>
        algorithm.Trim().ToLowerInvariant() switch
        {
            "sha256" => Convert.ToHexString(SHA256.HashData(content)).ToLowerInvariant(),
            "sha1" => Convert.ToHexString(SHA1.HashData(content)).ToLowerInvariant(),
            "sha512" => Convert.ToHexString(SHA512.HashData(content)).ToLowerInvariant(),
            _ => string.Empty,
        };

    public static string ComputeSha256(string content) =>
        DigestBytes(System.Text.Encoding.UTF8.GetBytes(content ?? string.Empty));

    public static string ComputeFileSha256(string filePath) =>
        SharedInstance.ComputeFileHash(filePath);

    public string ComputeFileHash(
        string filePath,
        string algorithm = "sha256",
        bool useCache = true,
        long maxBytes = DefaultMaxBytes)
    {
        if (string.IsNullOrWhiteSpace(filePath) || maxBytes < 0)
        {
            return string.Empty;
        }

        string normalizedAlgorithm = algorithm.Trim().ToLowerInvariant();
        using var hashAlgorithm = CreateAlgorithm(normalizedAlgorithm);
        if (hashAlgorithm is null)
        {
            return string.Empty;
        }

        try
        {
            var fileInfo = new FileInfo(filePath);
            if (!fileInfo.Exists || fileInfo.Length > maxBytes)
            {
                return string.Empty;
            }

            var key = new CacheKey(
                fileInfo.FullName,
                normalizedAlgorithm,
                fileInfo.Length,
                fileInfo.LastWriteTimeUtc.Ticks,
                maxBytes);
            if (useCache && cache.TryGetValue(key, out string? cached))
            {
                return cached;
            }

            using var stream = new FileStream(
                fileInfo.FullName,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                64 * 1024,
                FileOptions.SequentialScan);
            string digest = Convert.ToHexString(hashAlgorithm.ComputeHash(stream)).ToLowerInvariant();
            if (useCache)
            {
                if (cache.Count >= MaxCacheEntries)
                {
                    cache.TryRemove(cache.Keys.FirstOrDefault(), out _);
                }

                cache[key] = digest;
            }

            return digest;
        }
        catch (IOException)
        {
            return string.Empty;
        }
        catch (UnauthorizedAccessException)
        {
            return string.Empty;
        }
    }

    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有檔案雜湊相容性，不作為新的安全簽章或密碼用途")]
    private static HashAlgorithm? CreateAlgorithm(string algorithm) => algorithm.Trim().ToLowerInvariant() switch
    {
        "sha1" => SHA1.Create(),
        "sha256" => SHA256.Create(),
        "sha512" => SHA512.Create(),
        _ => null,
    };

    private readonly record struct CacheKey(string Path, string Algorithm, long Length, long LastWriteTicks, long MaxBytes);
}
