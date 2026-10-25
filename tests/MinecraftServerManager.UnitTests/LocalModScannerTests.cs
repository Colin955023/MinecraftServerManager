using System.IO.Compression;
using System.Text;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 本地模組檔案掃描與詮釋資料解析測試
/// </summary>
public sealed class LocalModScannerTests : IDisposable
{
    private readonly string _testDir;
    private readonly string _modsDir;

    public LocalModScannerTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_test_scanner_" + Guid.NewGuid().ToString("N"));
        _modsDir = Path.Combine(_testDir, "mods");
        Directory.CreateDirectory(_modsDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testDir))
            {
                Directory.Delete(_testDir, recursive: true);
            }
        }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
    }

    [Fact]
    public async Task ScanModsWithFabricModJsonShouldExtractMetadataCorrectly()
    {
        string jarPath = Path.Combine(_modsDir, "fabric-example-1.0.0.jar");
        CreateZipWithEntry(jarPath, "fabric.mod.json", """
        {
            "schemaVersion": 1,
            "id": "fabric_example",
            "version": "1.0.0",
            "name": "Fabric Example Mod",
            "description": "An example mod for fabric",
            "authors": ["TestAuthor"],
            "depends": {
                "fabricloader": ">=0.15.0",
                "minecraft": "~1.20.1"
            }
        }
        """);

        var persistence = new ModIndexPersistence(_testDir);
        var scanner = new LocalModScanner(persistence);
        var mods = await scanner.ScanModsAsync(_modsDir);

        var mod = Assert.Single(mods);
        Assert.Equal("fabric_example", mod.Id);
        Assert.Equal("Fabric Example Mod", mod.Name);
        Assert.Equal("1.0.0", mod.Version);
        Assert.Equal(ModPlatform.Local, mod.Platform);
        Assert.Equal("fabric", mod.LoaderType);
        Assert.Equal("TestAuthor", mod.Author);
        Assert.Equal("1.20.1", mod.MinecraftVersion);
    }

    [Fact]
    public async Task ScanModsWithForgeModsTomlShouldExtractMetadataCorrectly()
    {
        string jarPath = Path.Combine(_modsDir, "forge-mod-2.0.0.jar.disabled");
        CreateZipWithEntry(jarPath, "META-INF/mods.toml", """
        modLoader="javafml"
        loaderVersion="[47,)"
        [[mods]]
        modId="forge_test"
        version="2.0.0"
        displayName="Forge Test Mod"
        authors="ForgeDev"
        description="A test mod for Forge"
        """);

        var persistence = new ModIndexPersistence(_testDir);
        var scanner = new LocalModScanner(persistence);
        var mods = await scanner.ScanModsAsync(_modsDir);

        var mod = Assert.Single(mods);
        Assert.Equal("forge_test", mod.Id);
        Assert.Equal("Forge Test Mod", mod.Name);
        Assert.Equal("2.0.0", mod.Version);
        Assert.Equal(ModPlatform.Local, mod.Platform);
        Assert.Equal("forge", mod.LoaderType);
        Assert.Equal("ForgeDev", mod.Author);
        Assert.Equal(ModStatus.Disabled, mod.Status);
    }

    [Fact]
    public async Task ScanModsWithFilenameFallbackShouldInferIdAndVersion()
    {
        string jarPath = Path.Combine(_modsDir, "jei-1.20.1-forge-15.2.0.27.jar");
        CreateZipWithEntry(jarPath, "META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n");

        var persistence = new ModIndexPersistence(_testDir);
        var scanner = new LocalModScanner(persistence);
        var mods = await scanner.ScanModsAsync(_modsDir);

        var mod = Assert.Single(mods);
        Assert.Equal("jei", mod.Id);
        Assert.Equal("jei", mod.Name);
        Assert.Equal("1.20.1-forge-15.2.0.27", mod.Version);
        Assert.Equal(ModStatus.Enabled, mod.Status);
    }

    [Fact]
    public async Task ScanModsWithForgeTomlDependenciesShouldExtractMinecraftVersionCorrectly()
    {
        string jarPath = Path.Combine(_modsDir, "complex-forge-mod.jar");
        CreateZipWithEntry(jarPath, "META-INF/mods.toml", $"""
        modLoader="javafml"
        loaderVersion="[47,)"
        [[mods]]
        modId="complex_mod"
        version="1.5.0"
        displayName="§aComplex §eMod"
        description="A mod with \u001b[31mcolor\u001b[0m"

        [[dependencies.complex_mod]]
        modId="forge"
        mandatory=true
        versionRange="[47.1.0,)"

        [[dependencies.complex_mod]]
        modId="minecraft"
        mandatory=true
        versionRange="[1.20.1, 1.21)"
        ordering="NONE"
        side="BOTH"
        """);

        var persistence = new ModIndexPersistence(_testDir);
        var scanner = new LocalModScanner(persistence);
        var mods = await scanner.ScanModsAsync(_modsDir);

        var mod = Assert.Single(mods);
        Assert.Equal("complex_mod", mod.Id);
        Assert.Equal("Complex Mod", mod.Name);
        Assert.Equal("A mod with color", mod.Description);
        Assert.Equal("1.20.1", mod.MinecraftVersion);
    }

    [Fact]
    public async Task ScanModsWithJarInJarShouldExtractNestedMetadata()
    {
        string jarPath = Path.Combine(_modsDir, "connector-root.jar");
        using (var fileStream = new FileStream(jarPath, FileMode.Create))
        using (var archive = new ZipArchive(fileStream, ZipArchiveMode.Create))
        {
            var manifestEntry = archive.CreateEntry("META-INF/MANIFEST.MF");
            using (var writer = new StreamWriter(manifestEntry.Open(), Encoding.UTF8))
            {
                writer.WriteLine("Manifest-Version: 1.0");
                writer.WriteLine("Jar-In-Jar: META-INF/jarjar/nested-mod.jar");
            }

            var nestedEntry = archive.CreateEntry("META-INF/jarjar/nested-mod.jar");
            using (var nestedStream = nestedEntry.Open())
            using (var nestedArchive = new ZipArchive(nestedStream, ZipArchiveMode.Create, leaveOpen: true))
            {
                var fabricEntry = nestedArchive.CreateEntry("fabric.mod.json");
                using var fabricWriter = new StreamWriter(fabricEntry.Open(), Encoding.UTF8);
                fabricWriter.Write("""
                {
                    "schemaVersion": 1,
                    "id": "nested_mod",
                    "version": "1.0.0-beta.1",
                    "name": "Nested Fabric Mod",
                    "depends": {
                        "minecraft": "1.20.1"
                    }
                }
                """);
            }
        }

        var persistence = new ModIndexPersistence(_testDir);
        var scanner = new LocalModScanner(persistence);
        var mods = await scanner.ScanModsAsync(_modsDir);

        var mod = Assert.Single(mods);
        Assert.Equal("nested_mod", mod.Id);
        Assert.Equal("Nested Fabric Mod", mod.Name);
        Assert.Equal("1.0.0-beta.1", mod.Version);
        Assert.Equal("1.20.1", mod.MinecraftVersion);
    }

    [Fact]
    public async Task LegacyUnknownFormatInModIndex_IsParsedAndNormalizedCompatibly()
    {
        string jarPath = Path.Combine(_modsDir, "legacy-mod-1.0.jar");
        CreateZipWithEntry(jarPath, "fabric.mod.json", """
        {
            "schemaVersion": 1,
            "id": "legacy-mod",
            "name": "Legacy Mod",
            "version": "1.0.0"
        }
        """);

        FileInfo fileInfo = new(jarPath);
        ModIndexPersistence persistence = new(_testDir);
        Dictionary<string, string> legacyMeta = new(StringComparer.OrdinalIgnoreCase)
        {
            ["id"] = "legacy-mod",
            ["name"] = "Legacy Mod",
            ["version"] = "未知",
            ["mc_version"] = "unknown",
            ["loader_type"] = "未知"
        };
        persistence.CacheMetadata(Path.GetFileName(jarPath), legacyMeta, fileInfo.Length, fileInfo.LastWriteTimeUtc.Ticks);
        persistence.Flush();

        LocalModScanner scanner = new(persistence);
        IReadOnlyList<LocalModInfo> mods = await scanner.ScanModsAsync(_modsDir);

        LocalModInfo mod = Assert.Single(mods);
        Assert.Equal("legacy-mod", mod.Id);
        // 邊界回退依然產出一致的 "未知" 顯示，不致拋出例外且能正常運作
        Assert.Equal("未知", mod.Version);
        Assert.Equal("未知", mod.MinecraftVersion);
        Assert.Equal("未知", mod.LoaderType);
    }

    private static void CreateZipWithEntry(string zipPath, string entryName, string content)
    {
        using var fileStream = new FileStream(zipPath, FileMode.Create);
        using var archive = new ZipArchive(fileStream, ZipArchiveMode.Create);
        var entry = archive.CreateEntry(entryName);
        using var entryStream = entry.Open();
        using var writer = new StreamWriter(entryStream, Encoding.UTF8);
        writer.Write(content);
    }
}
