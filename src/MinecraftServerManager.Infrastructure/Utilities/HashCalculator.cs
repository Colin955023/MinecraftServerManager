using System.Buffers;
using System.Diagnostics.CodeAnalysis;
using System.Security.Cryptography;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Utilities;

public static class HashCalculator
{
    public const long DefaultMaxBytes = 512L * 1024 * 1024;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(HashCalculator));

    /// <summary>十六進位雜湊字元集合（大小寫皆可）</summary>
    private static readonly SearchValues<char> HexDigits = SearchValues.Create("0123456789abcdefABCDEF");

    /// <summary>解析雜湊演算法名稱（sha1／sha256／sha512）與摘要長度</summary>
    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有模組雜湊比對相容性，不作為密碼用途")]
    public static bool TryResolveAlgorithm(string? algorithm, out HashAlgorithmName name, out int hexLength)
    {
        ReadOnlySpan<char> value = algorithm.AsSpan().Trim();
        if (value.Equals(HashAlgorithmNames.Sha256, StringComparison.OrdinalIgnoreCase))
        {
            name = HashAlgorithmName.SHA256;
            hexLength = SHA256.HashSizeInBytes * 2;
            return true;
        }

        if (value.Equals(HashAlgorithmNames.Sha512, StringComparison.OrdinalIgnoreCase))
        {
            name = HashAlgorithmName.SHA512;
            hexLength = SHA512.HashSizeInBytes * 2;
            return true;
        }

        if (value.Equals(HashAlgorithmNames.Sha1, StringComparison.OrdinalIgnoreCase))
        {
            name = HashAlgorithmName.SHA1;
            hexLength = SHA1.HashSizeInBytes * 2;
            return true;
        }

        name = default;
        hexLength = 0;
        return false;
    }

    /// <summary>文字是否為指定演算法長度之十六進位摘要</summary>
    public static bool IsHexDigest(ReadOnlySpan<char> value, int expectedHexLength) =>
        expectedHexLength > 0 && value.Length == expectedHexLength && !value.ContainsAnyExcept(HexDigits);

    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有模組雜湊比對相容性，不作為密碼用途")]
    public static string DigestBytes(ReadOnlySpan<byte> content, string algorithm = HashAlgorithmNames.Sha256)
    {
        if (!TryResolveAlgorithm(algorithm, out var algName, out _))
        {
            return string.Empty;
        }

        Span<byte> hash = stackalloc byte[64];
        int bytesWritten = CryptographicOperations.HashData(algName, content, hash);
        return Convert.ToHexStringLower(hash[..bytesWritten]);
    }

    public static async Task<string> ComputeFileHashAsync(
        string filePath,
        string algorithm = HashAlgorithmNames.Sha256,
        long maxBytes = DefaultMaxBytes,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(filePath) || maxBytes < 0)
        {
            return string.Empty;
        }

        if (!TryResolveAlgorithm(algorithm, out var algName, out _))
        {
            return string.Empty;
        }

        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            using var stream = SafeFileSystem.OpenRead(
                filePath,
                FileShare.Read,
                FileOptions.SequentialScan | FileOptions.Asynchronous);
            if (stream.Length > maxBytes)
            {
                Logger.Warning("檔案超過雜湊計算大小上限 ({Length} > {MaxBytes}): {Path}", stream.Length, maxBytes, filePath);
                return string.Empty;
            }

            return await HashStreamAsync(stream, algName, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "計算檔案雜湊失敗: {Path}", filePath);
            return string.Empty;
        }
    }

    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有檔案雜湊相容性，不作為新的安全簽章或密碼用途")]
    private static async Task<string> HashStreamAsync(Stream stream, HashAlgorithmName algorithm, CancellationToken cancellationToken) =>
        Convert.ToHexStringLower(await CryptographicOperations.HashDataAsync(algorithm, stream, cancellationToken).ConfigureAwait(false));
}
