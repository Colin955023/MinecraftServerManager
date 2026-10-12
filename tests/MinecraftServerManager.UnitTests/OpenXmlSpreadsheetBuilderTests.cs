using System.IO.Compression;
using System.Text;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class OpenXmlSpreadsheetBuilderTests
{
    [Fact]
    public void GetExcelColumnName_ReturnsCorrectColumnIdentifiers()
    {
        Assert.Equal("A", OpenXmlSpreadsheetBuilder.GetExcelColumnName(1));
        Assert.Equal("B", OpenXmlSpreadsheetBuilder.GetExcelColumnName(2));
        Assert.Equal("Z", OpenXmlSpreadsheetBuilder.GetExcelColumnName(26));
        Assert.Equal("AA", OpenXmlSpreadsheetBuilder.GetExcelColumnName(27));
        Assert.Equal("AB", OpenXmlSpreadsheetBuilder.GetExcelColumnName(28));
        Assert.Equal("AZ", OpenXmlSpreadsheetBuilder.GetExcelColumnName(52));
        Assert.Equal("BA", OpenXmlSpreadsheetBuilder.GetExcelColumnName(53));
    }

    [Fact]
    public void NormalizeSheetName_CleansSpecialCharsAndTruncates()
    {
        Assert.Equal("Sheet1", OpenXmlSpreadsheetBuilder.NormalizeSheetName(null));
        Assert.Equal("Sheet1", OpenXmlSpreadsheetBuilder.NormalizeSheetName("   "));
        Assert.Equal("My_Sheet_Test", OpenXmlSpreadsheetBuilder.NormalizeSheetName("My[Sheet]Test"));
        Assert.Equal("CleanName", OpenXmlSpreadsheetBuilder.NormalizeSheetName("'CleanName'"));

        string longName = new('A', 50);
        string normalized = OpenXmlSpreadsheetBuilder.NormalizeSheetName(longName);
        Assert.Equal(31, normalized.Length);
    }

    [Fact]
    public void SanitizeXmlText_RemovesControlCharacters()
    {
        string raw = "Hello\x00\x01\x08World\t\r\nEnd\x1F";
        string sanitized = OpenXmlSpreadsheetBuilder.SanitizeXmlText(raw);

        Assert.Equal("HelloWorld\t\r\nEnd", sanitized);
    }

    [Fact]
    public void BuildWorkbook_ProducesValidZipWithRequiredOpenXmlEntries()
    {
        var rows = new List<IReadOnlyList<string>>
        {
            new[] { "狀態", "模組名稱", "版本" },
            new[] { "啟用", "Fabric API", "0.92.0" },
            new[] { "停用", "Sodium", "0.5.8" }
        };

        byte[] xlsxBytes = OpenXmlSpreadsheetBuilder.BuildWorkbook("模組清單", rows);

        Assert.NotNull(xlsxBytes);
        Assert.True(xlsxBytes.Length > 0);

        using var memoryStream = new MemoryStream(xlsxBytes);
        using var archive = new ZipArchive(memoryStream, ZipArchiveMode.Read);

        var entryNames = archive.Entries.Select(e => e.FullName).ToHashSet(StringComparer.OrdinalIgnoreCase);

        Assert.Contains("[Content_Types].xml", entryNames);
        Assert.Contains("_rels/.rels", entryNames);
        Assert.Contains("xl/workbook.xml", entryNames);
        Assert.Contains("xl/_rels/workbook.xml.rels", entryNames);
        Assert.Contains("xl/worksheets/sheet1.xml", entryNames);

        var sheetEntry = archive.GetEntry("xl/worksheets/sheet1.xml");
        Assert.NotNull(sheetEntry);
        using var sheetStream = sheetEntry.Open();
        using var reader = new StreamReader(sheetStream, Encoding.UTF8);
        string sheetContent = reader.ReadToEnd();

        Assert.Contains("Fabric API", sheetContent);
        Assert.Contains("Sodium", sheetContent);
        Assert.Contains("0.92.0", sheetContent);
    }
}
