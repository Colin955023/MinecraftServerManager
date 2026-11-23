using System.Security.Cryptography;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

public sealed class CoreUtilityTests
{
    [Theory]
    [InlineData("v1.6.6", "1.6.6")]
    [InlineData("1.7.0-beta.1", "1.7.0-beta.1")]
    [InlineData("  V2.0.1+build7  ", "2.0.1+build7")]
    [InlineData("1", "1.0.0")]
    [InlineData("1.20.1.4", "1.20.1.4")]
    [InlineData("1.20.1.0", "1.20.1")]
    public void VersionValueTryParse_SupportedVersion_Normalizes(string input, string expected)
    {
        Assert.True(VersionValue.TryParse(input, out var version));
        Assert.Equal(expected, version.ToString());
    }

    [Fact]
    public void VersionValueTryParse_InvalidInput_ReturnsFalse() => Assert.False(VersionValue.TryParse("version-x.y.z", out _));

    [Theory]
    [InlineData(0, "0 B")]
    [InlineData(1024, "1.0 KiB")]
    [InlineData(1048576, "1.0 MiB")]
    public void FormatBytes_VariousSizes_UsesBinaryUnits(long size, string expected) => Assert.Equal(expected, UnitFormatter.FormatBytes(size));

    [Theory]
    [InlineData("sha1", 40)]
    [InlineData("SHA256", 64)]
    [InlineData(" sha512 ", 128)]
    public void TryResolveAlgorithm_SupportedName_ReturnsNameAndHexLength(string algorithm, int expectedHexLength)
    {
        Assert.True(HashCalculator.TryResolveAlgorithm(algorithm, out HashAlgorithmName name, out int hexLength));
        Assert.Equal(expectedHexLength, hexLength);
        Assert.False(string.IsNullOrEmpty(name.Name));
    }

    [Theory]
    [InlineData("md5")]
    [InlineData("sha-512")]
    [InlineData("")]
    [InlineData(null)]
    public void TryResolveAlgorithm_UnsupportedName_ReturnsFalse(string? algorithm)
    {
        Assert.False(HashCalculator.TryResolveAlgorithm(algorithm, out _, out int hexLength));
        Assert.Equal(0, hexLength);
    }

    [Fact]
    public void IsHexDigest_VariousInputs_ValidatesLengthAndCharacters()
    {
        Assert.True(HashCalculator.IsHexDigest(new string('a', 40), 40));
        Assert.False(HashCalculator.IsHexDigest(new string('a', 39), 40));
        Assert.False(HashCalculator.IsHexDigest(new string('g', 40), 40));
    }

    [Theory]
    [InlineData("fabric-api.jar", true, false)]
    [InlineData("Fabric-API.JAR", true, false)]
    [InlineData("sodium.jar.disabled", false, true)]
    [InlineData("readme.txt", false, false)]
    public void ModFileNameHelpers_Extensions_Classifies(string fileName, bool isJar, bool isDisabled)
    {
        Assert.Equal(isJar, ModHelpers.IsJarFileName(fileName));
        Assert.Equal(isDisabled, ModHelpers.IsDisabledModFileName(fileName));
        Assert.Equal(isJar || isDisabled, ModHelpers.IsModFileName(fileName));
    }

    [Fact]
    public void ModFileNameHelpers_Stem_ComposesFileNames()
    {
        Assert.Equal("lithium.jar", ModHelpers.ToEnabledModFileName("lithium"));
        Assert.Equal("lithium.jar.disabled", ModHelpers.ToDisabledModFileName("lithium"));
        Assert.Equal("lithium", ModHelpers.ModFilenameStem("lithium.jar.disabled"));
    }

    [Fact]
    public void SynchronousProgress_Report_InvokesInlineInOrder()
    {
        var received = new List<int>();
        int callerThread = Environment.CurrentManagedThreadId;
        int? handlerThread = null;
        IProgress<int> progress = new SynchronousProgress<int>(value =>
        {
            handlerThread = Environment.CurrentManagedThreadId;
            received.Add(value);
        });

        for (int i = 1; i <= 5; i++)
        {
            progress.Report(i);
        }

        Assert.Equal([1, 2, 3, 4, 5], received);
        Assert.Equal(callerThread, handlerThread);
    }

    [Fact]
    public async Task JsonCodecReadFile_ExceedsMaxBytes_ReturnsDefault()
    {
        using var directory = new TempDirectory("msm-json-");
        string file = Path.Combine(directory.FullName, "oversized.json");
        File.WriteAllText(file, """{"name":"server"}""");

        Assert.Null(JsonCodec.ReadFile<Dictionary<string, string>>(file, maxBytes: 4));
        Assert.NotNull(JsonCodec.ReadFile<Dictionary<string, string>>(file, maxBytes: 1024));
        Assert.Null(await JsonCodec.ReadFileAsync<Dictionary<string, string>>(file, maxBytes: 4, cancellationToken: TestContext.Current.CancellationToken));
        Assert.NotNull(await JsonCodec.ReadFileAsync<Dictionary<string, string>>(file, maxBytes: 1024, cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public void MemoryHelpers_Settings_ParsesAndResolvesMinimum()
    {
        Assert.Equal(4096, MemoryHelpers.ParseMemorySetting("-Xmx4G"));
        Assert.Equal(2048, MemoryHelpers.ParseMemorySetting("-Xmx2048m"));
        Assert.Equal(1024, MemoryHelpers.ParseMemorySetting("-Xmx1048576k"));
        Assert.Equal(2048, MemoryHelpers.ParseMemorySetting("-Xms2048M", "Xms"));
        Assert.Equal(4096, MemoryHelpers.ParseMemorySetting("-Xms1024M -Xmx4096M", "Xmx"));
        Assert.Equal(1024, MemoryHelpers.ParseMemorySetting("-Xms1024M -Xmx4096M", "Xms"));
        Assert.Null(MemoryHelpers.ParseMemorySetting("invalid"));
        Assert.Null(MemoryHelpers.ParseMemorySetting("-Xmx4G", "Xms"));
        Assert.True(MemoryHelpers.GetTotalSystemMemoryMb() > 0);

        Assert.Equal(
            "java -Xms1024M -Xmx4096M -jar server.jar nogui",
            MemoryHelpers.ApplyMemoryFlags("java -Xmx4096k -jar server.jar nogui", minMb: 1024, maxMb: 4096));
        Assert.Equal(
            "java -Xms1024M -Xmx8192M -jar server.jar",
            MemoryHelpers.ApplyMemoryFlags("java -Xms512M -Xmx2G -jar server.jar", minMb: 1024, maxMb: 8192));

        Assert.Equal(256, MemoryHelpers.ResolveEffectiveMinMemoryMb(null, 256));
        Assert.Equal(ServerDefaults.DefaultMemoryMinMb, MemoryHelpers.ResolveEffectiveMinMemoryMb(null, 65536));
        Assert.Equal(777, MemoryHelpers.ResolveEffectiveMinMemoryMb(777, 65536));
    }

    [Theory]
    [InlineData("4096", "2048", MemoryCheckLevel.Ok)]
    [InlineData("abc", "", MemoryCheckLevel.Error)]
    [InlineData("0", "", MemoryCheckLevel.Error)]
    [InlineData("2048", "4096", MemoryCheckLevel.Error)]
    [InlineData("32768", "", MemoryCheckLevel.Error)]
    [InlineData("12288", "1024", MemoryCheckLevel.Warning)]
    public void CheckServerMemory_Boundaries_ReportsResult(string max, string min, MemoryCheckLevel expected)
    {
        var result = MemoryHelpers.CheckServerMemory(max, min, systemMemoryMb: 16384);
        Assert.Equal(expected, result.Level);
        if (expected != MemoryCheckLevel.Error)
        {
            Assert.Equal(int.Parse(max, System.Globalization.CultureInfo.InvariantCulture), result.MaxMb);
        }
    }

    [Fact]
    public void CheckServerMemory_ClampRequested_ClampsToSystemMemory()
    {
        var result = MemoryHelpers.CheckServerMemory("32768", "20000", systemMemoryMb: 16384, clampToSystem: true);

        Assert.Equal(MemoryCheckLevel.Warning, result.Level);
        Assert.Equal(16384, result.MaxMb);
        Assert.Equal(16384, result.MinMb);
        Assert.Contains("已自動調整", result.Message);
    }

    [Fact]
    public void MinecraftVersionSemantics_VariousVersions_DetectsAndCleans()
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
        Assert.Equal("26.1", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("26.1.0.0-alpha.1+snapshot-1"));
        Assert.Equal("26.1.2", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("26.1.2.36-beta"));
        Assert.Equal("26.3", MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge("26.3.0.101"));
    }

    [Fact]
    public void VersionValueParseOrZero_FourthSegment_Compares()
    {
        Assert.True(VersionValue.ParseOrZero("26.3.0.101") > VersionValue.ParseOrZero("26.3.0.99"));
        Assert.True(VersionValue.ParseOrZero("26.3.0.1") > VersionValue.ParseOrZero("26.3.0"));
        Assert.Equal("26.3.0.101", VersionValue.ParseOrZero("26.3.0.101").ToString());
        Assert.Equal("26.3.0", VersionValue.ParseOrZero("26.3.0.0").ToString());
    }

    [Fact]
    public void RecommendGcArgs_JavaAndMemory_RecommendsGcOptions()
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
