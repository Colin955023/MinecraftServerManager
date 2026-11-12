using System.Buffers;
using System.Globalization;
using System.IO.Compression;
using System.Security;
using System.Text;
using MinecraftServerManager.Core.Mods;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 使用 .NET 原生 ZipArchive 與標準 OpenXML 規範建置單工作表 Excel (.xlsx) 檔案。
/// 零外部相依性、極致輕量且安全過濾 XML 1.0 非法控制字元。
/// </summary>
public static class OpenXmlSpreadsheetBuilder
{
    private static readonly SearchValues<char> InvalidSheetNameChars = SearchValues.Create("[]:*?/\\");
    private static readonly string[] CachedColumnNames = [.. Enumerable.Range(1, 100).Select(ComputeExcelColumnName)];

    /// <summary>將字串表格建立為標準 OpenXML SpreadsheetML (.xlsx) 二進位位元組陣列。</summary>
    /// <param name="sheetName">工作表名稱（預設為「Sheet1」）。</param>
    /// <param name="rows">資料列集合，每列為儲存格字串清單。</param>
    /// <returns>合法的 XLSX 壓縮檔位元組陣列。</returns>
    public static byte[] BuildWorkbook(string sheetName, IReadOnlyList<IReadOnlyList<string>> rows)
    {
        ArgumentNullException.ThrowIfNull(rows);

        string safeSheetName = NormalizeSheetName(sheetName);
        string escapedSheetName = SecurityElement.Escape(safeSheetName) ?? "Sheet1";
        string workbookXml =
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
            "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" " +
            "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">" +
            $"<sheets><sheet name=\"{escapedSheetName}\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>";

        const string contentTypesXml =
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">" +
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>" +
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>" +
            "<Override PartName=\"/xl/workbook.xml\" " +
            "ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>" +
            "<Override PartName=\"/xl/worksheets/sheet1.xml\" " +
            "ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>" +
            "</Types>";

        const string rootRelsXml =
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
            "<Relationship Id=\"rId1\" " +
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" " +
            "Target=\"xl/workbook.xml\"/>" +
            "</Relationships>";

        const string workbookRelsXml =
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
            "<Relationship Id=\"rId1\" " +
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" " +
            "Target=\"worksheets/sheet1.xml\"/>" +
            "</Relationships>";

        using var memoryStream = new MemoryStream();
        using (var archive = new ZipArchive(memoryStream, ZipArchiveMode.Create, leaveOpen: true))
        {
            WriteEntry(archive, "[Content_Types].xml", contentTypesXml);
            WriteEntry(archive, "_rels/.rels", rootRelsXml);
            WriteEntry(archive, "xl/workbook.xml", workbookXml);
            WriteEntry(archive, "xl/_rels/workbook.xml.rels", workbookRelsXml);

            // 直寫 xl/worksheets/sheet1.xml 串流，避免巨量字串配置；文字經過濾與跳脫後輸出
            var sheetEntry = archive.CreateEntry("xl/worksheets/sheet1.xml", CompressionLevel.Optimal);
            using var writer = new StreamWriter(sheetEntry.Open(), new UTF8Encoding(false));
            writer.Write(
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>");

            for (int rowIndex = 0; rowIndex < rows.Count; rowIndex++)
            {
                var row = rows[rowIndex];
                string excelRowNum = (rowIndex + 1).ToString(CultureInfo.InvariantCulture);
                writer.Write($"<row r=\"{excelRowNum}\">");
                for (int colIndex = 0; colIndex < row.Count; colIndex++)
                {
                    writer.Write($"<c r=\"{GetExcelColumnName(colIndex + 1)}{excelRowNum}\" t=\"inlineStr\"><is><t xml:space=\"preserve\">");
                    writer.Write(SecurityElement.Escape(SanitizeXmlText(row[colIndex])));
                    writer.Write("</t></is></c>");
                }

                writer.Write("</row>");
            }

            writer.Write("</sheetData></worksheet>");
        }

        return memoryStream.ToArray();
    }

    private static void WriteEntry(ZipArchive archive, string entryName, string content)
    {
        var entry = archive.CreateEntry(entryName, CompressionLevel.Optimal);
        using var stream = entry.Open();
        using var writer = new StreamWriter(stream);
        writer.Write(content);
    }

    /// <summary>計算 1-indexed 數字對應的 Excel 欄名（例如 1 -> A, 26 -> Z, 27 -> AA）。</summary>
    public static string GetExcelColumnName(int columnNumber)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(columnNumber);
        if (columnNumber <= CachedColumnNames.Length)
        {
            return CachedColumnNames[columnNumber - 1];
        }

        return ComputeExcelColumnName(columnNumber);
    }

    private static string ComputeExcelColumnName(int columnNumber)
    {
        Span<char> buffer = stackalloc char[4];
        int pos = buffer.Length;
        int current = columnNumber;

        while (current > 0)
        {
            int remainder = (current - 1) % 26;
            buffer[--pos] = (char)('A' + remainder);
            current = (current - 1) / 26;
        }

        return new string(buffer[pos..]);
    }

    /// <summary>正規化 Excel 工作表名稱，移除不合法字元並截斷至 31 字元以內。</summary>
    public static string NormalizeSheetName(string? sheetName)
    {
        if (string.IsNullOrWhiteSpace(sheetName))
        {
            return "Sheet1";
        }

        string validText = RemoveInvalidXmlRunes(sheetName);
        var sb = new StringBuilder(validText.Length);
        foreach (char c in validText)
        {
            if (InvalidSheetNameChars.Contains(c))
            {
                sb.Append('_');
            }
            else
            {
                sb.Append(c);
            }
        }

        string cleaned = sb.ToString().Trim('\'').Trim();
        if (cleaned.Length > 31)
        {
            cleaned = cleaned[..(char.IsHighSurrogate(cleaned[30]) ? 30 : 31)].Trim();
        }

        return string.IsNullOrEmpty(cleaned) ? "Sheet1" : cleaned;
    }

    /// <summary>清洗文字中 XML 1.0 不允許的控制字元（除 \t, \n, \r 外之 0x00-0x1F）。</summary>
    public static string SanitizeXmlText(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        return RemoveInvalidXmlRunes(ModHelpers.StripColorAndFormattingCodes(text));
    }

    /// <summary>移除 XML 1.0 不允許之字元（含孤立代理字元），保留合法代理字對（如 emoji）。</summary>
    private static string RemoveInvalidXmlRunes(string text)
    {
        int firstInvalid = IndexOfInvalidXmlRune(text);
        if (firstInvalid < 0)
        {
            return text;
        }

        var sb = new StringBuilder(text.Length);
        sb.Append(text, 0, firstInvalid);
        ReadOnlySpan<char> remaining = text.AsSpan(firstInvalid);
        while (!remaining.IsEmpty)
        {
            OperationStatus status = Rune.DecodeFromUtf16(remaining, out Rune rune, out int consumed);
            if (status == OperationStatus.Done && IsValidXmlRune(rune))
            {
                sb.Append(remaining[..consumed]);
            }

            remaining = remaining[consumed..];
        }

        return sb.ToString();
    }

    /// <summary>以 Unicode 純量值逐一檢查，回傳第一個 XML 1.0 不允許字元（含孤立代理字元）之索引；全部合法時回傳 -1。</summary>
    private static int IndexOfInvalidXmlRune(ReadOnlySpan<char> text)
    {
        int index = 0;
        while (index < text.Length)
        {
            OperationStatus status = Rune.DecodeFromUtf16(text[index..], out Rune rune, out int consumed);
            if (status != OperationStatus.Done || !IsValidXmlRune(rune))
            {
                return index;
            }

            index += consumed;
        }

        return -1;
    }

    private static bool IsValidXmlRune(Rune rune) =>
        rune.Value is 0x9 or 0xA or 0xD or (>= 0x20 and <= 0xD7FF) or (>= 0xE000 and <= 0xFFFD) or >= 0x10000;
}
