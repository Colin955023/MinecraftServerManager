using System.Security.Cryptography;
using System.Text;
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
    public void VersionParserNormalizesSupportedVersions(string input, string expected)
    {
        Assert.True(VersionValue.TryParse(input, out var version));
        Assert.Equal(expected, version.ToString());
    }

    [Fact]
    public void VersionParserUsesFallbackForInvalidInput()
    {
        Assert.Equal(VersionValue.Zero, VersionValue.ParseOrDefault("version-x.y.z", VersionValue.Zero));
        Assert.Null(VersionValue.ParseOrDefault("version-x.y.z"));
    }

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
    public void HashCalculatorReturnsEmptyForUnsupportedAlgorithmOrOversizedFile()
    {
        var directory = Directory.CreateTempSubdirectory("msm-tests-");
        try
        {
            string file = Path.Combine(directory.FullName, "sample.bin");
            File.WriteAllText(file, "content");
            var calculator = new HashCalculator();

            Assert.Empty(calculator.ComputeFileHash(file, "md5"));
            Assert.Empty(calculator.ComputeFileHash(file, maxBytes: 1));
        }
        finally
        {
            directory.Delete(true);
        }
    }

    [Fact]
    public void MemoryUtilsParsesAndFormatsCorrectly()
    {
        Assert.Equal(4096, MemoryUtils.ParseMemorySetting("-Xmx4G"));
        Assert.Equal(2048, MemoryUtils.ParseMemorySetting("-Xms2048M", "Xms"));
        Assert.Null(MemoryUtils.ParseMemorySetting("invalid"));
        Assert.Null(MemoryUtils.ParseMemorySetting("-Xmx4G", "Xms"));

        Assert.Equal("4G", MemoryUtils.FormatMemoryMb(4096, compact: true));
        Assert.Equal("1.5G", MemoryUtils.FormatMemoryMb(1536, compact: true));
        Assert.Equal("512M", MemoryUtils.FormatMemoryMb(512, compact: true));
        Assert.Equal("4.0 GB", MemoryUtils.FormatMemoryMb(4096, compact: false));
    }

    [Fact]
    public void MemoryUtilsValidatesServerMemoryBoundaries()
    {
        var valid = MemoryUtils.ValidateAndNormalizeServerMemory("4096", "2048", totalMemoryMb: 16384);
        Assert.True(valid.IsValid);
        Assert.Equal(4096, valid.MemoryMaxMb);
        Assert.Equal(2048, valid.MemoryMinMb);
        Assert.False(valid.AdjustedMax);

        var belowMin = MemoryUtils.ValidateAndNormalizeServerMemory("512");
        Assert.False(belowMin.IsValid);
        Assert.Equal("最大記憶體不可低於 1024 MB", belowMin.ErrorMessage);

        var minGreaterThanMax = MemoryUtils.ValidateAndNormalizeServerMemory("2048", "4096");
        Assert.False(minGreaterThanMax.IsValid);
        Assert.Equal("最小記憶體不可大於最大記憶體", minGreaterThanMax.ErrorMessage);

        var exceedsTotal = MemoryUtils.ValidateAndNormalizeServerMemory("32768", totalMemoryMb: 16384);
        Assert.True(exceedsTotal.IsValid);
        Assert.True(exceedsTotal.AdjustedMax);
        Assert.Equal(16384, exceedsTotal.MemoryMaxMb);
        Assert.NotEmpty(exceedsTotal.WarningMessages);
    }

    [Fact]
    public void MinecraftVersionSemanticsDetectsAndCleansCorrectly()
    {
        Assert.True(MinecraftVersionSemantics.IsFabricCompatible("1.20.4"));
        Assert.True(MinecraftVersionSemantics.IsFabricCompatible("1.14"));
        Assert.False(MinecraftVersionSemantics.IsFabricCompatible("1.12.2"));

        Assert.Equal("fabric", MinecraftVersionSemantics.StandardizeLoaderType("Fabric"));
        Assert.Equal("vanilla", MinecraftVersionSemantics.StandardizeLoaderType("原版"));
        Assert.Equal("forge", MinecraftVersionSemantics.StandardizeLoaderType("unknown", "47.2.0"));

        Assert.Equal("0.5.8", MinecraftVersionSemantics.CleanModVersion("0.5.8+mc1.20.4"));
        Assert.Equal("1.0.0", MinecraftVersionSemantics.CleanModVersion("1.0.0-fabric-beta"));

        Assert.Equal("1.20.4", MinecraftVersionSemantics.ExtractMinecraftVersionFromText("fabric-server-mc1.20.4.jar"));
        Assert.Equal("fabric", MinecraftVersionSemantics.DetectLoaderFromText("Running fabric server"));

        Assert.Equal("1.20.1", MinecraftVersionSemantics.NormalizeMinecraftVersion("~1.20.1"));
        Assert.Equal("1.20.1", MinecraftVersionSemantics.NormalizeMinecraftVersion(">=1.20.1"));
        Assert.Equal("1.20.4", MinecraftVersionSemantics.NormalizeMinecraftVersion("1.20.4"));
        Assert.Equal(string.Empty, MinecraftVersionSemantics.NormalizeMinecraftVersion(null));
    }

    [Fact]
    public void JvmOptionPolicyRecommendsGarbageCollectorOptions()
    {
        var g1Args = JvmOptionPolicy.RecommendGcArgs(4096, javaMajor: 17);
        Assert.Contains("-XX:+UseG1GC", g1Args);

        var zgcArgs = JvmOptionPolicy.RecommendGcArgs(4096, javaMajor: 21);
        Assert.Contains("-XX:+UseZGC", zgcArgs);

        string[] existing = new[] { "-XX:+UseParallelGC" };
        var suppressed = JvmOptionPolicy.RecommendGcArgs(4096, javaMajor: 21, existingArgs: existing);
        Assert.Empty(suppressed);
    }

    [Fact]
    public void ModSemanticsSelectsBestModVersion()
    {
        Assert.Equal("sha512", ModSemantics.NormalizeHashAlgorithm("SHA-512"));
        Assert.True(ModSemantics.IsAllowedVersionType("release"));
        Assert.True(ModSemantics.IsAllowedVersionType("beta"));
        Assert.False(ModSemantics.IsAllowedVersionType("alpha"));

        var vAlpha = new Domain.Mods.OnlineModVersion("1", "1.0", "Alpha", versionType: "alpha", files: [new Domain.Mods.ModFile("a.jar")]);
        var vBeta = new Domain.Mods.OnlineModVersion("2", "1.1", "Beta", versionType: "beta", files: [new Domain.Mods.ModFile("b.jar")]);
        var vRelease = new Domain.Mods.OnlineModVersion("3", "1.2", "Release", versionType: "release", files: [new Domain.Mods.ModFile("c.jar")]);

        var best = ModSemantics.SelectBestModVersion([vAlpha, vRelease, vBeta]);
        Assert.NotNull(best);
        Assert.Equal("3", best.VersionId);
    }
}

