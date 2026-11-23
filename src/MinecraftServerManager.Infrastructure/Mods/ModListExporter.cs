using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組清單匯出（純文字、JSON、HTML、XLSX）</summary>
public sealed class ModListExporter : IModListExporter
{
    private const string EmptyPlaceholder = "-";
    private const string SheetName = "模組清單";
    /// <summary>HTML 與 XLSX 共用欄位標題</summary>
    private static readonly string[] Headers =
        ["啟用狀態", "模組名稱", "版本", "Minecraft版本", "載入器", "作者", "檔案名稱", "模組ID", "檔案大小", "修改時間", "描述"];

    // 每列輸出長度估計，用於預先配置 StringBuilder 容量
    private const int EstimatedTextRowLength = 96;
    private const int EstimatedHtmlRowLength = 512;

    public async Task ExportAsync(
        IReadOnlyList<ModListExportRow> rows,
        ModListExportFormat format,
        string filePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(rows);
        ArgumentException.ThrowIfNullOrWhiteSpace(filePath);
        cancellationToken.ThrowIfCancellationRequested();

        if (format == ModListExportFormat.Xlsx)
        {
            byte[] workbook = await Task.Run(() => BuildXlsx(rows), cancellationToken).ConfigureAwait(false);
            await SafeFileSystem.WriteAllBytesAsync(filePath, workbook, cancellationToken).ConfigureAwait(false);
            return;
        }

        Func<IReadOnlyList<ModListExportRow>, string> builder = format switch
        {
            ModListExportFormat.Json => BuildJson,
            ModListExportFormat.Html => BuildHtml,
            ModListExportFormat.Text => BuildText,
            _ => throw new ArgumentOutOfRangeException(nameof(format), format, "不支援的匯出格式")
        };

        string content = await Task.Run(() => builder(rows), cancellationToken).ConfigureAwait(false);

        // JSON 不寫 BOM（部分解析器拒絕），文字與 HTML 保留 BOM 以利記事本辨識編碼
        Encoding? encoding = format == ModListExportFormat.Json ? null : Encoding.UTF8;
        await SafeFileSystem.WriteAllTextAsync(filePath, content, encoding, cancellationToken).ConfigureAwait(false);
    }

    private static string Clean(string value) =>
        value == EmptyPlaceholder ? string.Empty : ModHelpers.StripColorAndFormattingCodes(value);

    /// <summary>匯出前每列僅清洗一次（移除色碼並將預留位置轉為空字串），各格式與 JSON 序列化共用</summary>
    internal readonly record struct CleanRow(
        [property: JsonPropertyName("enabled")] bool IsEnabled,
        [property: JsonPropertyName("name")] string Name,
        [property: JsonPropertyName("version")] string Version,
        [property: JsonPropertyName("minecraftVersion")] string MinecraftVersion,
        [property: JsonPropertyName("loaderType")] string LoaderType,
        [property: JsonPropertyName("author")] string Author,
        [property: JsonPropertyName("filename")] string FileName,
        [property: JsonPropertyName("id")] string Id,
        [property: JsonPropertyName("fileSize")] string FileSize,
        [property: JsonPropertyName("modifiedTime")] string ModifiedTime,
        [property: JsonPropertyName("description")] string Description);

    private static CleanRow Sanitize(ModListExportRow m) => new(
        m.IsEnabled,
        ModHelpers.StripColorAndFormattingCodes(m.Name),
        ModHelpers.StripColorAndFormattingCodes(m.Version),
        Clean(m.MinecraftVersion),
        Clean(m.LoaderType),
        Clean(m.Author),
        ModHelpers.StripColorAndFormattingCodes(m.FileName),
        ModHelpers.StripColorAndFormattingCodes(m.Id),
        Clean(m.FileSize),
        Clean(m.ModifiedTime),
        ModHelpers.StripColorAndFormattingCodes(m.Description));

    private static string BuildJson(IReadOnlyList<ModListExportRow> rows) =>
        JsonCodec.SerializeRelaxed<List<CleanRow>>([.. rows.Select(Sanitize)]);

    private static string BuildHtml(IReadOnlyList<ModListExportRow> rows)
    {
        var sb = new StringBuilder(1024 + (rows.Count * EstimatedHtmlRowLength));
        sb.AppendLine("<!DOCTYPE html>");
        sb.AppendLine("<html lang=\"zh-TW\">");
        sb.AppendLine("<head><meta charset=\"UTF-8\"><title>模組清單</title>");
        sb.AppendLine("<style>table{border-collapse:collapse;width:100%;}th,td{border:1px solid silver;padding:6px;text-align:left;}th{background:whitesmoke;}.status-badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:0.85em;font-weight:600;border:1px solid transparent;}.status-enabled{background:#e6f4ea;color:#137333;border-color:#a8dab5;}.status-disabled{background:#fce8e6;color:#c5221f;border-color:#f6aea9;}</style>");
        sb.AppendLine("</head><body>");
        sb.AppendLine("<h2>模組清單</h2>");
        sb.AppendLine("<table>");
        sb.Append("<tr>");
        foreach (string header in Headers)
        {
            sb.Append("<th>").Append(header).Append("</th>");
        }

        sb.AppendLine("</tr>");

        foreach (ModListExportRow m in rows)
        {
            CleanRow c = Sanitize(m);
            string statusHtml = c.IsEnabled
                ? "<span class=\"status-badge status-enabled\">啟用</span>"
                : "<span class=\"status-badge status-disabled\">停用</span>";
            sb.AppendLine(CultureInfo.InvariantCulture,
                $"<tr><td>{statusHtml}</td><td>{WebUtility.HtmlEncode(c.Name)}</td><td>{WebUtility.HtmlEncode(c.Version)}</td><td>{WebUtility.HtmlEncode(c.MinecraftVersion)}</td><td>{WebUtility.HtmlEncode(c.LoaderType)}</td><td>{WebUtility.HtmlEncode(c.Author)}</td><td>{WebUtility.HtmlEncode(c.FileName)}</td><td>{WebUtility.HtmlEncode(c.Id)}</td><td>{WebUtility.HtmlEncode(c.FileSize)}</td><td>{WebUtility.HtmlEncode(c.ModifiedTime)}</td><td>{WebUtility.HtmlEncode(c.Description)}</td></tr>");
        }

        sb.AppendLine("</table></body></html>");
        return sb.ToString();
    }

    private static byte[] BuildXlsx(IReadOnlyList<ModListExportRow> rows)
    {
        var table = new List<IReadOnlyList<string>>(rows.Count + 1) { Headers };
        foreach (ModListExportRow m in rows)
        {
            CleanRow c = Sanitize(m);
            // 每一欄皆防公式注入
            table.Add([
                c.IsEnabled ? "是" : "否",
                SanitizeSpreadsheetFormula(c.Name),
                SanitizeSpreadsheetFormula(c.Version),
                SanitizeSpreadsheetFormula(c.MinecraftVersion),
                SanitizeSpreadsheetFormula(c.LoaderType),
                SanitizeSpreadsheetFormula(c.Author),
                SanitizeSpreadsheetFormula(c.FileName),
                SanitizeSpreadsheetFormula(c.Id),
                SanitizeSpreadsheetFormula(c.FileSize),
                SanitizeSpreadsheetFormula(c.ModifiedTime),
                SanitizeSpreadsheetFormula(c.Description),
            ]);
        }

        return OpenXmlSpreadsheetBuilder.BuildWorkbook(SheetName, table);
    }

    /// <summary>略過前導空白後以公式字元或控制字元開頭時加上單引號，避免試算表執行公式</summary>
    internal static string SanitizeSpreadsheetFormula(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return string.Empty;
        }

        ReadOnlySpan<char> trimmed = value.AsSpan().TrimStart(' ');
        if (trimmed.IsEmpty)
        {
            return value;
        }

        return trimmed[0] is '=' or '+' or '-' or '@' or '\t' or '\r' or '\n' ? "'" + value : value;
    }

    private static string BuildText(IReadOnlyList<ModListExportRow> rows)
    {
        var sb = new StringBuilder(32 + (rows.Count * EstimatedTextRowLength));
        sb.AppendLine("# 模組清單");
        sb.AppendLine();

        foreach (ModListExportRow m in rows)
        {
            CleanRow c = Sanitize(m);
            string statusTag = c.IsEnabled ? "[啟用]" : "[停用]";
            string authorPart = !string.IsNullOrWhiteSpace(c.Author) ? $" - by {c.Author}" : string.Empty;
            sb.AppendLine(CultureInfo.InvariantCulture, $"{statusTag} {c.Name} ({c.Version}){authorPart}");
        }

        return sb.ToString();
    }
}
