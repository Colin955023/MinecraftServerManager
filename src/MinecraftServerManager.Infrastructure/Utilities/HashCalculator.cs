using System.Buffers;
using System.Diagnostics.CodeAnalysis;
using System.Security.Cryptography;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

public static class HashCalculator
{
    public const long DefaultMaxBytes = 512L * 1024 * 1024;

    /// <summary>十六進位雜湊字元集合（大小寫皆可）</summary>
    private static readonly SearchValues<char> HexDigits = SearchValues.Create("0123456789abcdefABCDEF");

    /// <summary>雜湊演算法名稱的唯一解析入口：支援 sha1／sha256／sha512（不分大小寫），並回傳對應十六進位摘要長度。</summary>
    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有模組雜湊比對相容性，不作為密碼用途")]
    public static bool TryResolveAlgorithm(string? algorithm, out HashAlgorithmName name, out int hexLength)
    {
        ReadOnlySpan<char> value = algorithm.AsSpan().Trim();
        if (value.Equals("sha256", StringComparison.OrdinalIgnoreCase))
        {
            name = HashAlgorithmName.SHA256;
            hexLength = SHA256.HashSizeInBytes * 2;
            return true;
        }

        if (value.Equals("sha512", StringComparison.OrdinalIgnoreCase))
        {
            name = HashAlgorithmName.SHA512;
            hexLength = SHA512.HashSizeInBytes * 2;
            return true;
        }

        if (value.Equals("sha1", StringComparison.OrdinalIgnoreCase))
        {
            name = HashAlgorithmName.SHA1;
            hexLength = SHA1.HashSizeInBytes * 2;
            return true;
        }

        name = default;
        hexLength = 0;
        return false;
    }

    /// <summary>判斷文字是否為指定演算法長度之十六進位摘要</summary>
    public static bool IsHexDigest(ReadOnlySpan<char> value, int expectedHexLength) =>
        expectedHexLength > 0 && value.Length == expectedHexLength && !value.ContainsAnyExcept(HexDigits);

    [SuppressMessage(
        "Security",
        "CA5350",
        Justification = "SHA-1 僅保留給既有模組雜湊比對相容性，不作為密碼用途")]
    public static string DigestBytes(ReadOnlySpan<byte> content, string algorithm = "sha256")
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
        string algorithm = "sha256",
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

        try
        {
            using var stream = SafeFileSystem.OpenRead(
                filePath,
                FileShare.Read,
                FileOptions.SequentialScan | FileOptions.Asynchronous);
            if (stream.Length > maxBytes)
            {
                return string.Empty;
            }

            return await HashStreamAsync(stream, algName, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
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
