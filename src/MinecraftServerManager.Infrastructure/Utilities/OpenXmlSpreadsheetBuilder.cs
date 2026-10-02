using System.Buffers;
using System.Globalization;
using System.IO.Compression;
using System.Security;
using System.Text;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 使用 .NET 原生 ZipArchive 與標準 OpenXML 規範建置單工作表 Excel (.xlsx) 檔案。
/// 零外部依賴、極致輕量且安全過濾 XML 1.0 非法控制字元。
/// </summary>
public static class OpenXmlSpreadsheetBuilder
{
    private static readonly SearchValues<char> InvalidSheetNameChars = SearchValues.Create("[]:*?/\\");

    /// <summary>
    /// 將字串表格建立為標準 OpenXML SpreadsheetML (.xlsx) 二進位位元組陣列。
    /// </summary>
    /// <param name="sheetName">工作表名稱（預設為「Sheet1」）。</param>
    /// <param name="rows">資料列集合，每列為單元格字串清單。</param>
    /// <returns>合法的 XLSX 壓縮檔位元組陣列。</returns>
    public static byte[] BuildWorkbook(string sheetName, IReadOnlyList<IReadOnlyList<string>> rows)
    {
        ArgumentNullException.ThrowIfNull(rows);

        string safeSheetName = NormalizeSheetName(sheetName);

        // 建置 sheet1.xml
        var sheetRows = new StringBuilder();
        for (int rowIndex = 0; rowIndex < rows.Count; rowIndex++)
        {
            var row = rows[rowIndex];
            int excelRowNum = rowIndex + 1;

            sheetRows.Append(CultureInfo.InvariantCulture, $"<row r=\"{excelRowNum}\">");
            for (int colIndex = 0; colIndex < row.Count; colIndex++)
            {
                string colName = GetExcelColumnName(colIndex + 1);
                string cellRef = $"{colName}{excelRowNum}";
                string cellValue = SanitizeXmlText(row[colIndex]);
                string escapedText = SecurityElement.Escape(cellValue) ?? string.Empty;

                sheetRows.Append(CultureInfo.InvariantCulture,
                    $"<c r=\"{cellRef}\" t=\"inlineStr\"><is><t xml:space=\"preserve\">{escapedText}</t></is></c>");
            }
            sheetRows.Append("</row>");
        }

        string sheetXml =
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
            "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">" +
            $"<sheetData>{sheetRows}</sheetData></worksheet>";

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
            WriteEntry(archive, "xl/worksheets/sheet1.xml", sheetXml);
        }

        return memoryStream.ToArray();
    }

    private static void WriteEntry(ZipArchive archive, string entryName, string content)
    {
        var entry = archive.CreateEntry(entryName, CompressionLevel.Optimal);
        using var stream = entry.Open();
        byte[] bytes = Encoding.UTF8.GetBytes(content);
        stream.Write(bytes, 0, bytes.Length);
    }

    /// <summary>
    /// 計算 1-indexed 數字對應的 Excel 欄名（例如 1 -> A, 26 -> Z, 27 -> AA）。
    /// </summary>
    public static string GetExcelColumnName(int columnNumber)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(columnNumber);

        string result = string.Empty;
        int current = columnNumber;

        while (current > 0)
        {
            int remainder = (current - 1) % 26;
            result = (char)('A' + remainder) + result;
            current = (current - 1) / 26;
        }

        return result;
    }

    /// <summary>
    /// 正規化 Excel 工作表名稱，移除不合法字元並截斷至 31 字元以內。
    /// </summary>
    public static string NormalizeSheetName(string? sheetName)
    {
        if (string.IsNullOrWhiteSpace(sheetName))
        {
            return "Sheet1";
        }

        var sb = new StringBuilder(sheetName.Length);
        foreach (char c in sheetName)
        {
            if (IsInvalidXmlChar(c))
            {
                continue;
            }

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
            cleaned = cleaned[..31].Trim();
        }

        return string.IsNullOrEmpty(cleaned) ? "Sheet1" : cleaned;
    }

    /// <summary>
    /// 清洗文字中 XML 1.0 不允許的控制字元（除 \t, \n, \r 外之 0x00-0x1F）。
    /// </summary>
    public static string SanitizeXmlText(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        bool hasInvalid = false;
        foreach (char c in text)
        {
            if (IsInvalidXmlChar(c))
            {
                hasInvalid = true;
                break;
            }
        }

        if (!hasInvalid)
        {
            return text;
        }

        var sb = new StringBuilder(text.Length);
        foreach (char c in text)
        {
            if (!IsInvalidXmlChar(c))
            {
                sb.Append(c);
            }
        }

        return sb.ToString();
    }

    private static bool IsInvalidXmlChar(char c)
    {
        // XML 1.0 規範合法字元包含 #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
        return c switch
        {
            '\t' or '\n' or '\r' => false,
            < ' ' => true,
            >= '\uD800' and <= '\uDFFF' => false, // 代理對由 .NET 字串處理
            '\uFFFE' or '\uFFFF' => true,
            _ => false
        };
    }
}
