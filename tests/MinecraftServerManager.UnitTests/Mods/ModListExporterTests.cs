using System.IO.Compression;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class ModListExporterTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm_test_export_");
    private readonly string _testDir;

    public ModListExporterTests()
    {
        _testDir = _testDirTemp.FullName;
    }

    public void Dispose() => _testDirTemp.Dispose();

    [Fact]
    public async Task ExportModListAsync_TextFormat_IncludesModDetails()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.txt");
        var rows = new List<ModListExportRow>
        {
            new("testmod", "Test Mod", "1.0.0", "testmod.jar", "10 KiB", "DevTeam", "fabric", "1.20.1", "2026-01-01", "A test mod", true),
            new("disabledmod", "Disabled Mod", "0.9.0", "disabledmod.jar.disabled", "5 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", false)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Text, filePath, TestContext.Current.CancellationToken);
        string text = await File.ReadAllTextAsync(filePath, TestContext.Current.CancellationToken);

        Assert.Contains("# 模組清單", text, StringComparison.Ordinal);
        Assert.Contains("[啟用] Test Mod (1.0.0) - by DevTeam", text, StringComparison.Ordinal);
        Assert.Contains("[停用] Disabled Mod (0.9.0)", text, StringComparison.Ordinal);
        Assert.DoesNotContain("✅", text, StringComparison.Ordinal);
        Assert.DoesNotContain("❌", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsync_XlsxFormat_ProducesValidWorkbook()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.xlsx");
        var rows = new List<ModListExportRow>
        {
            new("my-mod", "My, Mod", "2.1.0", "my-mod.jar", "20 KiB", "AuthorOne", "forge", "1.20.1", "2026-01-01", "Desc", true),
            new("off-mod", "Off Mod", "1.0.0", "off-mod.jar.disabled", "8 KiB", "AuthorTwo", "forge", "1.20.1", "2026-01-01", "Off", false)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Xlsx, filePath, TestContext.Current.CancellationToken);

        Assert.True(File.Exists(filePath));
        Assert.True(new FileInfo(filePath).Length > 0);

        using var archive = ZipFile.OpenRead(filePath);
        string sheet = string.Concat(archive.Entries.Where(static e => e.FullName.EndsWith(".xml", StringComparison.Ordinal)).Select(static e =>
        {
            using var reader = new StreamReader(e.Open());
            return System.Net.WebUtility.HtmlDecode(reader.ReadToEnd());
        }));

        Assert.Contains("是", sheet, StringComparison.Ordinal);
        Assert.Contains("否", sheet, StringComparison.Ordinal);
        Assert.Contains("My, Mod", sheet, StringComparison.Ordinal);
        Assert.Contains("Off Mod", sheet, StringComparison.Ordinal);
        Assert.DoesNotContain("✅", sheet, StringComparison.Ordinal);
        Assert.DoesNotContain("❌", sheet, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsync_JsonFormat_ProducesValidJson()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.json");
        var rows = new List<ModListExportRow>
        {
            new("mod", "Mod", "1.0", "mod.jar", "10 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Json, filePath, TestContext.Current.CancellationToken);
        string json = await File.ReadAllTextAsync(filePath, TestContext.Current.CancellationToken);

        Assert.StartsWith("[", json.Trim(), StringComparison.Ordinal);
        Assert.Contains("\"id\": \"mod\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsync_JsonFormat_KeepsPlusQuoteAndAmpersand()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "clean_chars.json");
        var rows = new List<ModListExportRow>
        {
            new("mod_plus", "Create Crafts & Additions", "2.5.1+mc1.20.1", "Connector-1.0.0+1.20.1.jar", "10 KiB", "Let's Do", "forge", "1.20.1", "2026-01-01", "you're 30+ easings", true)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Json, filePath, TestContext.Current.CancellationToken);
        string json = await File.ReadAllTextAsync(filePath, TestContext.Current.CancellationToken);

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
    public async Task ExportModListAsync_JsonFormat_HasNoBom()
    {
        string filePath = Path.Combine(_testDir, "nobom.json");
        await new ModListExporter().ExportAsync(
            [new("mod", "Mod", "1.0", "mod.jar", "10 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", true)],
            ModListExportFormat.Json, filePath, TestContext.Current.CancellationToken);

        byte[] bytes = await File.ReadAllBytesAsync(filePath, TestContext.Current.CancellationToken);
        Assert.NotEqual(0xEF, bytes[0]);
    }

    [Fact]
    public async Task ExportModListAsync_UnknownFormat_Rejects() =>
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => new ModListExporter().ExportAsync(
            [], (ModListExportFormat)99, Path.Combine(_testDir, "x.out"), TestContext.Current.CancellationToken));

    [Theory]
    [InlineData("=SUM(A1)", "'=SUM(A1)")]
    [InlineData("  =cmd", "'  =cmd")]
    [InlineData("\nline", "'\nline")]
    [InlineData("-1", "'-1")]
    [InlineData("Sodium", "Sodium")]
    [InlineData("   ", "   ")]
    public void SanitizeSpreadsheetFormula_FormulaPrefix_Escapes(string input, string expected) =>
        Assert.Equal(expected, ModListExporter.SanitizeSpreadsheetFormula(input));

    [Fact]
    public async Task ExportModListAsync_HtmlFormat_ContainsTable()
    {
        var exporter = new ModListExporter();
        string filePath = Path.Combine(_testDir, "mods.html");
        var rows = new List<ModListExportRow>
        {
            new("mod", "Mod", "1.0", "mod.jar", "10 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", true),
            new("mod-off", "Mod Off", "0.5", "mod-off.jar.disabled", "4 KiB", "-", "fabric", "1.20.1", "2026-01-01", "", false)
        };

        await exporter.ExportAsync(rows, ModListExportFormat.Html, filePath, TestContext.Current.CancellationToken);
        string html = await File.ReadAllTextAsync(filePath, TestContext.Current.CancellationToken);

        Assert.Contains("<table>", html, StringComparison.Ordinal);
        Assert.Contains("<th>模組名稱</th>", html, StringComparison.Ordinal);
        Assert.Contains(".status-badge", html, StringComparison.Ordinal);
        Assert.Contains(".status-enabled", html, StringComparison.Ordinal);
        Assert.Contains(".status-disabled", html, StringComparison.Ordinal);
        Assert.Contains("<span class=\"status-badge status-enabled\">啟用</span>", html, StringComparison.Ordinal);
        Assert.Contains("<span class=\"status-badge status-disabled\">停用</span>", html, StringComparison.Ordinal);
        Assert.DoesNotContain("✅", html, StringComparison.Ordinal);
        Assert.DoesNotContain("❌", html, StringComparison.Ordinal);
    }

    private static ModListExportRow Row(string name, string description = "", string author = "-", bool enabled = true) =>
        new("mod", name, "1.0", "mod.jar", "10 KiB", author, "fabric", "1.20.1", "2026-01-01", description, enabled);

    [Fact]
    public async Task ExportAsync_HtmlWithMarkup_EncodesUserContent()
    {
        string filePath = Path.Combine(_testDir, "xss.html");

        await new ModListExporter().ExportAsync(
            [Row("<script>alert(1)</script>", "\"onmouseover=x\" & <img src=x onerror=y>", "<b>me</b>")],
            ModListExportFormat.Html, filePath, TestContext.Current.CancellationToken);
        string html = await File.ReadAllTextAsync(filePath, TestContext.Current.CancellationToken);

        Assert.DoesNotContain("<script>", html, StringComparison.Ordinal);
        Assert.DoesNotContain("<img", html, StringComparison.Ordinal);
        Assert.DoesNotContain("<b>me</b>", html, StringComparison.Ordinal);
        Assert.Contains("&lt;script&gt;alert(1)&lt;/script&gt;", html, StringComparison.Ordinal);
        Assert.Contains("&quot;onmouseover=x&quot; &amp; &lt;img", html, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportAsync_XlsxWithFormulaPrefixes_EscapesEveryCell()
    {
        string filePath = Path.Combine(_testDir, "formula.xlsx");

        await new ModListExporter().ExportAsync(
            [Row("=HYPERLINK(\"http://x\")", "+cmd|' /C calc'!A0", "@SUM(A1)")],
            ModListExportFormat.Xlsx, filePath, TestContext.Current.CancellationToken);

        using var archive = ZipFile.OpenRead(filePath);
        string sheet = string.Concat(archive.Entries.Where(static e => e.FullName.EndsWith(".xml", StringComparison.Ordinal)).Select(static e =>
        {
            using var reader = new StreamReader(e.Open());
            return System.Net.WebUtility.HtmlDecode(reader.ReadToEnd());
        }));

        Assert.Contains("'=HYPERLINK", sheet, StringComparison.Ordinal);
        Assert.Contains("'+cmd", sheet, StringComparison.Ordinal);
        Assert.Contains("'@SUM(A1)", sheet, StringComparison.Ordinal);
        Assert.DoesNotContain("<f>", sheet, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(ModListExportFormat.Text)]
    [InlineData(ModListExportFormat.Html)]
    public async Task ExportAsync_TextAndHtml_WriteUtf8Bom(ModListExportFormat format)
    {
        string filePath = Path.Combine(_testDir, "bom.out");

        await new ModListExporter().ExportAsync([Row("Mod")], format, filePath, TestContext.Current.CancellationToken);
        byte[] bytes = await File.ReadAllBytesAsync(filePath, TestContext.Current.CancellationToken);

        Assert.Equal([0xEF, 0xBB, 0xBF], bytes[..3]);
    }

    [Fact]
    public async Task ExportAsync_PlaceholderAndColorCodes_AreCleaned()
    {
        string filePath = Path.Combine(_testDir, "clean.json");

        await new ModListExporter().ExportAsync(
            [Row("§aGreen Mod", "§lBold", "-", enabled: false)],
            ModListExportFormat.Json,
            filePath,
            TestContext.Current.CancellationToken);
        string json = await File.ReadAllTextAsync(filePath, TestContext.Current.CancellationToken);

        Assert.Contains("\"name\": \"Green Mod\"", json, StringComparison.Ordinal);
        Assert.Contains("\"description\": \"Bold\"", json, StringComparison.Ordinal);
        Assert.Contains("\"author\": \"\"", json, StringComparison.Ordinal);
        Assert.Contains("\"enabled\": false", json, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportAsync_CanceledToken_ThrowsWithoutWriting()
    {
        string filePath = Path.Combine(_testDir, "canceled.txt");

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            new ModListExporter().ExportAsync([Row("Mod")], ModListExportFormat.Text, filePath, new CancellationToken(canceled: true)));
        Assert.False(File.Exists(filePath));
    }
}
