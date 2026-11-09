using System.Diagnostics.CodeAnalysis;
using System.Security.Cryptography;
using System.Text;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class HashCalculatorTests
{
    [Theory]
    [InlineData("")]
    [InlineData("hello world")]
    [InlineData("1234567890!@#$%^&*()_+")]
    [InlineData("繁體中文與台灣用詞測試內容一二三四五六七八九十")]
    public void ComputeSha256_ProducesExactMatchWithStandardCrypto(string input)
    {
        string actual = HashCalculator.ComputeSha256(input);
        byte[] expectedBytes = SHA256.HashData(Encoding.UTF8.GetBytes(input ?? string.Empty));
        string expected = Convert.ToHexStringLower(expectedBytes);

        Assert.Equal(expected, actual);
    }

    [Fact]
    public void ComputeSha256_LargeString_ProducesExactMatch()
    {
        string input = new('A', 5000);
        string actual = HashCalculator.ComputeSha256(input);
        byte[] expectedBytes = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        string expected = Convert.ToHexStringLower(expectedBytes);

        Assert.Equal(expected, actual);
    }

    [Fact]
    [SuppressMessage("Security", "CA5350", Justification = "測試 SHA-1 演算法相容性")]
    public void DigestBytes_SupportedAlgorithms_ProducesCorrectOutputs()
    {
        byte[] data = "test content"u8.ToArray();

        string sha256 = HashCalculator.DigestBytes(data, "sha256");
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(data)), sha256);

        string sha1 = HashCalculator.DigestBytes(data, "sha1");
        Assert.Equal(Convert.ToHexStringLower(SHA1.HashData(data)), sha1);

        string sha512 = HashCalculator.DigestBytes(data, "sha512");
        Assert.Equal(Convert.ToHexStringLower(SHA512.HashData(data)), sha512);

        string unknown = HashCalculator.DigestBytes(data, "md5");
        Assert.Equal(string.Empty, unknown);
    }
}
