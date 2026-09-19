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
        catch
        {
        }
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

        Assert.Single(mods);
        var mod = mods[0];
        Assert.Equal("fabric_example", mod.Id);
        Assert.Equal("Fabric Example Mod", mod.Name);
        Assert.Equal("1.0.0", mod.Version);
        Assert.Equal(ModPlatform.Local, mod.Platform);
        Assert.Equal("fabric", mod.LoaderType);
        Assert.Equal("TestAuthor", mod.Author);
        Assert.Equal("1.20.1", mod.MinecraftVersion);
        Assert.Equal(ModStatus.Enabled, mod.Status);
        Assert.NotEmpty(mod.CurrentHash);
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

        Assert.Single(mods);
        var mod = mods[0];
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

        Assert.Single(mods);
        var mod = mods[0];
        Assert.Equal("jei", mod.Id);
        Assert.Equal("jei", mod.Name);
        Assert.Equal("1.20.1-forge-15.2.0.27", mod.Version);
        Assert.Equal(ModStatus.Enabled, mod.Status);
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
