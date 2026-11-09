using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Security.Cryptography;
using System.Text.Json;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 共用工具入口（統一工具調度）行為測試：驗證各能力的唯一入口實作正確
/// </summary>
public sealed class SharedToolEntryTests : IDisposable
{
    private readonly string _tempDir = Path.Combine(Path.GetTempPath(), "MSM_SharedToolTests_" + Guid.NewGuid().ToString("N"));

    public SharedToolEntryTests() => Directory.CreateDirectory(_tempDir);

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDir))
            {
                Directory.Delete(_tempDir, recursive: true);
            }
        }
        catch (IOException ex)
        {
            AppLogging.CreateComponentLogger(nameof(SharedToolEntryTests)).Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

    [Theory]
    [InlineData(@"Z:\outside\file.txt")]
    [InlineData(@"\\server\share\file.txt")]
    public void IsPathWithinRejectsTargetsOnDifferentRoot(string target) =>
        Assert.False(SafeFileSystem.IsPathWithin(_tempDir, target, strict: false));

    [Fact]
    public void SanitizeXmlTextKeepsEmojiAndRemovesInvalidCharacters()
    {
        string input = "Mod 🎮 名稱\u0001\uD800尾";

        string sanitized = OpenXmlSpreadsheetBuilder.SanitizeXmlText(input);

        Assert.Equal("Mod 🎮 名稱尾", sanitized);
    }

    [Theory]
    [InlineData("sha1", 40)]
    [InlineData("SHA256", 64)]
    [InlineData(" sha512 ", 128)]
    public void TryResolveAlgorithmReturnsNameAndHexLength(string algorithm, int expectedHexLength)
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
    public void TryResolveAlgorithmRejectsUnsupportedNames(string? algorithm)
    {
        Assert.False(HashCalculator.TryResolveAlgorithm(algorithm, out _, out int hexLength));
        Assert.Equal(0, hexLength);
    }

    [Fact]
    public void IsHexDigestValidatesLengthAndCharacters()
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
    public void ModFileNameHelpersClassifyExtensions(string fileName, bool isJar, bool isDisabled)
    {
        Assert.Equal(isJar, ModHelpers.IsJarFileName(fileName));
        Assert.Equal(isDisabled, ModHelpers.IsDisabledModFileName(fileName));
        Assert.Equal(isJar || isDisabled, ModHelpers.IsModFileName(fileName));
    }

    [Fact]
    public void ModFileNameHelpersComposeFileNamesFromStem()
    {
        Assert.Equal("lithium.jar", ModHelpers.ToEnabledModFileName("lithium"));
        Assert.Equal("lithium.jar.disabled", ModHelpers.ToDisabledModFileName("lithium"));
        Assert.Equal("lithium", ModHelpers.ModFilenameStem("lithium.jar.disabled"));
    }

    [Fact]
    public void SynchronousProgressReportsInlineAndInOrder()
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

    [Theory]
    [InlineData("paper", LoaderKind.Paper)]
    [InlineData(" NeoForge ", LoaderKind.NeoForge)]
    [InlineData("VANILLA", LoaderKind.Vanilla)]
    public void LoaderKindsParsesDefinedNames(string value, LoaderKind expected)
    {
        Assert.True(LoaderKinds.TryParse(value, out var kind));
        Assert.Equal(expected, kind);
    }

    [Theory]
    [InlineData("2")]
    [InlineData("-1")]
    [InlineData("spigot")]
    [InlineData("")]
    [InlineData(null)]
    public void LoaderKindsRejectsNumericAndUnknownValues(string? value)
    {
        Assert.False(LoaderKinds.TryParse(value, out var kind));
        Assert.Equal(LoaderKind.Unknown, kind);
        Assert.Equal(LoaderKind.Vanilla, LoaderKinds.ParseOrDefault(value, LoaderKind.Vanilla));
    }

    [Theory]
    [InlineData("-Xmx4G", 4096)]
    [InlineData("-Xmx2048m", 2048)]
    [InlineData("-Xmx1048576k", 1024)]
    [InlineData("-Xmx1t", 1048576)]
    public void ParseMemorySettingSupportsAllJvmUnits(string text, int expectedMb) =>
        Assert.Equal(expectedMb, MemoryUtils.ParseMemorySetting(text));

    [Fact]
    public void ApplyMemoryFlagsRewritesAndInsertsMinimum()
    {
        string rewritten = MemoryUtils.ApplyMemoryFlags("java -Xmx4096k -jar server.jar nogui", minMb: 1024, maxMb: 4096);
        Assert.Equal("java -Xms1024M -Xmx4096M -jar server.jar nogui", rewritten);

        string both = MemoryUtils.ApplyMemoryFlags("java -Xms512M -Xmx2G -jar server.jar", minMb: 1024, maxMb: 8192);
        Assert.Equal("java -Xms1024M -Xmx8192M -jar server.jar", both);
    }

    [Fact]
    public void ResolveEffectiveMinMemoryUsesSmallerOfDefaultAndMax()
    {
        Assert.Equal(256, MemoryUtils.ResolveEffectiveMinMemoryMb(null, 256));
        Assert.Equal(ServerDefaults.DefaultMemoryMinMb, MemoryUtils.ResolveEffectiveMinMemoryMb(null, 65536));
        Assert.Equal(777, MemoryUtils.ResolveEffectiveMinMemoryMb(777, 65536));
    }

    [Fact]
    public void CreateTempSiblingPathStaysInTargetDirectory()
    {
        string target = Path.Combine(_tempDir, "settings.json");

        string first = AtomicFileWriter.CreateTempSiblingPath(target);
        string second = AtomicFileWriter.CreateTempSiblingPath(target);

        Assert.Equal(_tempDir, Path.GetDirectoryName(first));
        Assert.StartsWith(target + ".", first, StringComparison.Ordinal);
        Assert.EndsWith(AtomicFileWriter.TempFileExtension, first, StringComparison.Ordinal);
        Assert.NotEqual(first, second);
    }

    [Fact]
    public void MojangVersionCatalogParsesManifestAndFiltersServerJars()
    {
        const string manifest = """
        {
            "versions": [
                { "id": "1.21.4", "type": "release", "url": "https://example.com/1.21.4.json" },
                { "id": "1.2.4", "type": "release", "url": "https://example.com/1.2.4.json" },
                { "id": "24w05a", "type": "snapshot", "url": "https://example.com/24w05a.json" }
            ]
        }
        """;

        using var doc = JsonCodec.ParseDocument(manifest);
        var versions = MojangVersionCatalog.ParseManifest(doc);

        Assert.Contains(versions, static v => v.Version == "1.21.4" && v.Stable);
        Assert.Contains(versions, static v => v.Version == "24w05a" && !v.Stable);
        Assert.DoesNotContain(versions, static v => v.Version == "1.2.4");
    }

    [Fact]
    public void MojangVersionCatalogFindsCachedPackageUrl()
    {
        File.WriteAllText(
            MojangVersionCatalog.GetVersionsCachePath(_tempDir),
            """[{ "Version": "1.20.4", "Url": "https://example.com/1.20.4.json", "Stable": true }]""");

        Assert.Equal("https://example.com/1.20.4.json", MojangVersionCatalog.TryGetCachedPackageUrl(_tempDir, "1.20.4"));
        Assert.Null(MojangVersionCatalog.TryGetCachedPackageUrl(_tempDir, "1.19.2"));
        Assert.Equal("https://example.com/1.20.4.json", MojangVersionCatalog.GetCachedReleasePackageUrls(_tempDir)["1.20.4"]);
    }

    [Fact]
    public async Task MojangVersionCatalogFallsBackToSecondaryManifestUrl()
    {
        var http = new StubHttpPort(uri => uri.AbsoluteUri == MojangVersionCatalog.ManifestFallbackUrl
            ? """{ "versions": [ { "id": "1.20.1", "type": "release", "url": "https://example.com/1.20.1.json" } ] }"""
            : null);

        var versions = await MojangVersionCatalog.FetchManifestAsync(http, CancellationToken.None);

        Assert.NotNull(versions);
        Assert.Single(versions);
        Assert.Equal(2, http.RequestCount);
    }

    [Fact]
    public async Task MojangVersionCatalogAppliesJavaFloorForPaper()
    {
        var http = new StubHttpPort(static _ => """{ "version": { "java": { "version": { "minimum": 7 } } } }""");

        int? major = await MojangVersionCatalog.FetchPaperJavaMajorAsync(http, "1.8.8", CancellationToken.None);

        Assert.Equal(MojangVersionCatalog.MinimumJavaMajor, major);
    }

    [Fact]
    public void TableSortExtensionsSortsNaturallyInBothDirections()
    {
        var items = new ObservableCollection<SortRow>
        {
            new() { Name = "Server 10" },
            new() { Name = "Server 2" },
            new() { Name = "Server 1" },
        };

        var keys = new SortKeyMap<SortRow>((nameof(SortRow.Name), static r => r.Name));

        items.SortBy(keys, nameof(SortRow.Name), ListSortDirection.Ascending);
        Assert.Equal(["Server 1", "Server 2", "Server 10"], items.Select(static i => i.Name));

        items.SortBy(keys, nameof(SortRow.Name), ListSortDirection.Descending);
        Assert.Equal(["Server 10", "Server 2", "Server 1"], items.Select(static i => i.Name));

        // 未登錄欄位不排序
        items.SortBy(keys, "Unknown", ListSortDirection.Ascending);
        Assert.Equal(["Server 10", "Server 2", "Server 1"], items.Select(static i => i.Name));
    }

    [Fact]
    public void SourceScannerStripCommentsOnlyKeepsStringsAndLineLayout()
    {
        const string source = "string a = \"keep.tmp\"; // drop.tmp\r\n/* \"gone\" */ string b = \"// not comment\";";

        string commentsOnly = Architecture.SourceScanner.StripCommentsOnly(source);
        string both = Architecture.SourceScanner.StripCommentsAndStrings(source);

        Assert.Equal(source.Length, commentsOnly.Length);
        Assert.Contains("\"keep.tmp\"", commentsOnly, StringComparison.Ordinal);
        Assert.Contains("\"// not comment\"", commentsOnly, StringComparison.Ordinal);
        Assert.DoesNotContain("drop.tmp", commentsOnly, StringComparison.Ordinal);
        Assert.DoesNotContain("gone", commentsOnly, StringComparison.Ordinal);
        Assert.DoesNotContain("keep.tmp", both, StringComparison.Ordinal);
    }

    public sealed class SortRow
    {
        public string Name { get; init; } = string.Empty;
    }
}
