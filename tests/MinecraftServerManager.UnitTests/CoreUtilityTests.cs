using System.Security.Cryptography;
using System.Text;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class CoreUtilityTests
{
    [Theory]
    [InlineData("v1.6.6", "1.6.6")]
    [InlineData("1.7.0-beta.1", "1.7.0-beta.1")]
    [InlineData("  V2.0.1+build7  ", "2.0.1+build7")]
    [InlineData("1", "1.0.0")]
    [InlineData("1.20.1.4", "1.20.1")]
    public void VersionParserNormalizesSupportedVersions(string input, string expected)
    {
        Assert.True(VersionValue.TryParse(input, out var version));
        Assert.Equal(expected, version.ToString());
    }

    [Fact]
    public void VersionParserRejectsInvalidInput() => Assert.False(VersionValue.TryParse("version-x.y.z", out _));

    [Theory]
    [InlineData(0, "0 B")]
    [InlineData(1024, "1.0 KiB")]
    [InlineData(1048576, "1.0 MiB")]
    public void UnitFormatterUsesBinaryUnits(long size, string expected) => Assert.Equal(expected, UnitFormatter.FormatBytes(size));

    [Fact]
    public void HashCalculatorMatchesKnownSha256()
    {
        byte[] content = Encoding.UTF8.GetBytes("Minecraft Server Manager\n");
        string expected = Convert.ToHexString(SHA256.HashData(content)).ToLowerInvariant();

        Assert.Equal(expected, HashCalculator.DigestBytes(content));
    }

    [Fact]
    public async Task HashCalculatorReturnsEmptyForUnsupportedAlgorithmOrOversizedFile()
    {
        var directory = Directory.CreateTempSubdirectory("msm-tests-");
        try
        {
            string file = Path.Combine(directory.FullName, "sample.bin");
            File.WriteAllText(file, "content");
            var calculator = new HashCalculator();

            Assert.Empty(await calculator.ComputeFileHashAsync(file, "md5"));
            Assert.Empty(await calculator.ComputeFileHashAsync(file, maxBytes: 1));
        }
        finally
        {
            directory.Delete(true);
        }
    }

    [Fact]
    public void MemoryUtilsParsesCorrectly()
    {
        Assert.Equal(4096, MemoryUtils.ParseMemorySetting("-Xmx4G"));
        Assert.Equal(2048, MemoryUtils.ParseMemorySetting("-Xms2048M", "Xms"));
        Assert.Equal(4096, MemoryUtils.ParseMemorySetting("-Xms1024M -Xmx4096M", "Xmx"));
        Assert.Equal(1024, MemoryUtils.ParseMemorySetting("-Xms1024M -Xmx4096M", "Xms"));
        Assert.Null(MemoryUtils.ParseMemorySetting("invalid"));
        Assert.Null(MemoryUtils.ParseMemorySetting("-Xmx4G", "Xms"));
        Assert.True(MemoryUtils.GetTotalSystemMemoryMb() >= 4096);
    }

    [Theory]
    [InlineData("4096", "2048", MemoryCheckLevel.Ok)]
    [InlineData("abc", "", MemoryCheckLevel.Error)]
    [InlineData("0", "", MemoryCheckLevel.Error)]
    [InlineData("2048", "4096", MemoryCheckLevel.Error)]
    [InlineData("32768", "", MemoryCheckLevel.Error)]
    [InlineData("12288", "1024", MemoryCheckLevel.Warning)]
    public void MemoryUtilsChecksServerMemoryBoundaries(string max, string min, MemoryCheckLevel expected)
    {
        var result = MemoryUtils.CheckServerMemory(max, min, systemMemoryMb: 16384);
        Assert.Equal(expected, result.Level);
        if (expected != MemoryCheckLevel.Error)
        {
            Assert.Equal(int.Parse(max, System.Globalization.CultureInfo.InvariantCulture), result.MaxMb);
        }
    }

    [Fact]
    public void MemoryUtilsClampsToSystemMemoryWhenRequested()
    {
        var result = MemoryUtils.CheckServerMemory("32768", "20000", systemMemoryMb: 16384, clampToSystem: true);

        Assert.Equal(MemoryCheckLevel.Warning, result.Level);
        Assert.Equal(16384, result.MaxMb);
        Assert.Equal(16384, result.MinMb);
        Assert.Contains("已自動調整", result.Message);
    }

    [Fact]
    public void MinecraftVersionSemanticsDetectsAndCleansCorrectly()
    {
        Assert.True(MinecraftVersionSemantics.IsFabricCompatible("1.20.4"));
        Assert.True(MinecraftVersionSemantics.IsFabricCompatible("1.14"));
        Assert.False(MinecraftVersionSemantics.IsFabricCompatible("1.12.2"));

        Assert.Equal("1.20.4", MinecraftVersionSemantics.ExtractMinecraftVersionFromText("fabric-server-mc1.20.4.jar"));

        Assert.Equal("1.20.1", MinecraftVersionSemantics.NormalizeMinecraftVersion("~1.20.1"));
        Assert.Equal("1.20.1", MinecraftVersionSemantics.NormalizeMinecraftVersion(">=1.20.1"));
        Assert.Equal("1.20.4", MinecraftVersionSemantics.NormalizeMinecraftVersion("1.20.4"));
        Assert.Equal(string.Empty, MinecraftVersionSemantics.NormalizeMinecraftVersion(null));

        Assert.Equal("1.20.1", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("47.1.106"));
        Assert.Equal("1.21.1", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("21.1.77"));
        Assert.Equal("1.21", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("21.0.167"));
        Assert.Equal("26.1", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("26.1.0"));
    }

    [Fact]
    public void JvmOptionPolicyRecommendsGarbageCollectorOptions()
    {
        var g1Args = JvmOptionPolicy.RecommendGcArgs(4096, javaMajor: 17);
        Assert.Contains("-XX:+UseG1GC", g1Args);

        var zgcArgs = JvmOptionPolicy.RecommendGcArgs(4096, javaMajor: 21);
        Assert.Contains("-XX:+UseZGC", zgcArgs);

        string[] existing = ["-XX:+UseParallelGC"];
        var suppressed = JvmOptionPolicy.RecommendGcArgs(4096, javaMajor: 21, existingArgs: existing);
        Assert.Empty(suppressed);
    }
}
