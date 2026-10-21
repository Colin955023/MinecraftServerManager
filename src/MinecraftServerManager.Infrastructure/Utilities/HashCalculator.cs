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
            "sha256" => Convert.ToHexStringLower(SHA256.HashData(content)),
            "sha1" => Convert.ToHexStringLower(SHA1.HashData(content)),
            "sha512" => Convert.ToHexStringLower(SHA512.HashData(content)),
            _ => string.Empty,
        };

    public static string ComputeSha256(string content) =>
        DigestBytes(System.Text.Encoding.UTF8.GetBytes(content ?? string.Empty));

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
        if (normalizedAlgorithm is not ("sha256" or "sha1" or "sha512"))
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
            string digest = HashStream(stream, normalizedAlgorithm);
            if (useCache)
            {
                if (cache.Count >= MaxCacheEntries)
                {
                    using var enumerator = cache.GetEnumerator();
                    if (enumerator.MoveNext())
                    {
                        cache.TryRemove(enumerator.Current.Key, out _);
                    }
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
    private static string HashStream(Stream stream, string algorithm) => algorithm switch
    {
        "sha256" => Convert.ToHexStringLower(SHA256.HashData(stream)),
        "sha1" => Convert.ToHexStringLower(SHA1.HashData(stream)),
        "sha512" => Convert.ToHexStringLower(SHA512.HashData(stream)),
        _ => string.Empty,
    };

    private readonly record struct CacheKey(string Path, string Algorithm, long Length, long LastWriteTicks, long MaxBytes);
}
