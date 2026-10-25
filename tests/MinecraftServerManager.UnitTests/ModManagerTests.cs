using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組管理外觀服務測試
/// </summary>
public sealed class ModManagerTests : IDisposable
{
    private readonly string _testDir;

    public ModManagerTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_test_modmgr_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
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
    public async Task ExportModListAsyncTextFormatShouldIncludeModDetails()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.txt");
        var rows = new List<ModListExportRow>
        {
            new("testmod", "Test Mod", "1.0.0", "testmod.jar", "10 KiB", "DevTeam", "fabric", "1.20.1", "2026-01-01", "A test mod", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Text, filePath);
        string text = await File.ReadAllTextAsync(filePath);

        Assert.Contains("# 模組列表", text, StringComparison.Ordinal);
        Assert.Contains("Test Mod", text, StringComparison.Ordinal);
        Assert.Contains("DevTeam", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsyncXlsxFormatShouldProduceValidWorkbook()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.xlsx");
        var rows = new List<ModListExportRow>
        {
            new("my-mod", "My, Mod", "2.1.0", "my-mod.jar", "20 KiB", "AuthorOne", "forge", "1.20.1", "2026-01-01", "Desc", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Xlsx, filePath);

        Assert.True(File.Exists(filePath));
        Assert.True(new FileInfo(filePath).Length > 0);
    }

    [Fact]
    public async Task ExportModListAsyncJsonFormatShouldBeValidJson()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.json");
        var rows = new List<ModListExportRow>
        {
            new("mod", "Mod", "1.0", "mod.jar", "10 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Json, filePath);
        string json = await File.ReadAllTextAsync(filePath);

        Assert.StartsWith("[", json.Trim(), StringComparison.Ordinal);
        Assert.Contains("\"id\": \"mod\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsyncJsonFormatShouldNotEscapePlusQuoteAndAmpersand()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "clean_chars.json");
        var rows = new List<ModListExportRow>
        {
            new("mod_plus", "Create Crafts & Additions", "2.5.1+mc1.20.1", "Connector-1.0.0+1.20.1.jar", "10 KiB", "Let's Do", "forge", "1.20.1", "2026-01-01", "you're 30+ easings", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Json, filePath);
        string json = await File.ReadAllTextAsync(filePath);

        // 確保加號、單引號、與符號保持原樣，絕不出現 \u002B, \u0027, \u0026
        Assert.Contains("2.5.1+mc1.20.1", json, StringComparison.Ordinal);
        Assert.Contains("Connector-1.0.0+1.20.1.jar", json, StringComparison.Ordinal);
        Assert.Contains("Create Crafts & Additions", json, StringComparison.Ordinal);
        Assert.Contains("Let's Do", json, StringComparison.Ordinal);
        Assert.Contains("you're 30+ easings", json, StringComparison.Ordinal);
        Assert.DoesNotContain("\\u002B", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("\\u0027", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("\\u0026", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task ExportModListAsyncHtmlFormatShouldContainTable()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.html");
        var rows = new List<ModListExportRow>
        {
            new("mod", "Mod", "1.0", "mod.jar", "10 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Html, filePath);
        string html = await File.ReadAllTextAsync(filePath);

        Assert.Contains("<table>", html, StringComparison.Ordinal);
        Assert.Contains("<th>模組名稱</th>", html, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ModManagerDelegatesToScannerAndInstaller()
    {
        var sampleMods = new List<LocalModInfo>
        {
            new("testmod", "Test Mod", "testmod.jar", "1.0.0", "1.20.1", "fabric", author: "DevTeam", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var fakeScanner = new FakeScanner(sampleMods);
        var fakeInstaller = new FakeInstaller();
        var manager = new ModManager(fakeScanner, fakeInstaller);

        var mods = await manager.GetModsAsync(_testDir);
        var item = Assert.Single(mods);
        Assert.Equal("testmod", item.Id);
    }

    private sealed class FakeScanner(IReadOnlyList<LocalModInfo> mods) : ILocalModScanner
    {
        public Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods);

        public Task<LocalModInfo?> ScanSingleModAsync(string filePath, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods.Count > 0 ? mods[0] : null);
    }

    private sealed class FakeInstaller : IModFileInstaller
    {
        public Task<LocalModMutationResult> SetModStateAsync(string modsDirectory, string modId, bool enable, CancellationToken cancellationToken = default) =>
            Task.FromResult(LocalModMutationResult.Success("狀態變更成功"));

        public Task<LocalModMutationResult> DeleteModsAsync(string modsDirectory, IReadOnlyList<string> modIds, CancellationToken cancellationToken = default) =>
            Task.FromResult(LocalModMutationResult.Success("刪除成功"));

        public Task<LocalModMutationResult> ImportLocalModAsync(string modsDirectory, string sourceFilePath, CancellationToken cancellationToken = default) =>
            Task.FromResult(LocalModMutationResult.Success("匯入成功"));

        public Task<ModFileOperationResult> InstallRemoteModAsync(
            string modsDirectory,
            string downloadUrl,
            string fileName,
            string? expectedHash = null,
            string? hashAlgorithm = null,
            IProgress<int>? progress = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(ModFileOperationResult.Success(fileName, "安裝成功"));
    }
}
