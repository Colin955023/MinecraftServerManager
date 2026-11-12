using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組清單匯出實作（純文字、JSON、HTML、XLSX），內容組裝與檔案寫入皆於背景執行緒完成</summary>
public sealed class ModListExporter : IModListExporter
{
    private const string EmptyPlaceholder = "-";
    private const string SheetName = "模組清單";
    private static readonly string[] XlsxHeaders =
        ["啟用狀態", "模組名稱", "版本", "Minecraft版本", "載入器", "作者", "檔案名稱", "模組ID", "檔案大小", "修改時間", "描述"];

    /// <summary>將模組清單依指定格式匯出至檔案</summary>
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

        string content = await Task.Run(() => format switch
        {
            ModListExportFormat.Json => BuildJson(rows),
            ModListExportFormat.Html => BuildHtml(rows),
            _ => BuildText(rows),
        }, cancellationToken).ConfigureAwait(false);

        await SafeFileSystem.WriteAllTextAsync(filePath, content, Encoding.UTF8, cancellationToken).ConfigureAwait(false);
    }

    private static string Clean(string value) =>
        value == EmptyPlaceholder ? string.Empty : ModHelpers.StripColorAndFormattingCodes(value);

    /// <summary>匯出前每列僅清洗一次（移除色碼並將預留位置轉為空字串），各格式共用</summary>
    private readonly record struct CleanRow(
        bool IsEnabled,
        string Name,
        string Version,
        string MinecraftVersion,
        string LoaderType,
        string Author,
        string FileName,
        string Id,
        string FileSize,
        string ModifiedTime,
        string Description);

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

    private static string BuildJson(IReadOnlyList<ModListExportRow> rows)
    {
        List<ModJsonItem> items = [.. rows.Select(static m =>
        {
            CleanRow c = Sanitize(m);
            return new ModJsonItem(
                Name: c.Name,
                Version: c.Version,
                Enabled: c.IsEnabled,
                MinecraftVersion: c.MinecraftVersion,
                LoaderType: c.LoaderType,
                Author: c.Author,
                FileName: c.FileName,
                Id: c.Id,
                FileSize: c.FileSize,
                ModifiedTime: c.ModifiedTime,
                Description: c.Description);
        })];

        return JsonCodec.SerializeRelaxed(items);
    }

    private static string BuildHtml(IReadOnlyList<ModListExportRow> rows)
    {
        var sb = new StringBuilder();
        sb.AppendLine("<!DOCTYPE html>");
        sb.AppendLine("<html lang=\"zh-TW\">");
        sb.AppendLine("<head><meta charset=\"UTF-8\"><title>模組清單</title>");
        sb.AppendLine("<style>table{border-collapse:collapse;width:100%;}th,td{border:1px solid silver;padding:6px;text-align:left;}th{background:whitesmoke;}</style>");
        sb.AppendLine("</head><body>");
        sb.AppendLine("<h2>模組清單</h2>");
        sb.AppendLine("<table>");
        sb.AppendLine("<tr><th>啟用狀態</th><th>模組名稱</th><th>版本</th><th>MC版本</th><th>載入器</th><th>作者</th><th>檔案名稱</th><th>模組ID</th><th>檔案大小</th><th>修改時間</th><th>描述</th></tr>");

        foreach (ModListExportRow m in rows)
        {
            CleanRow c = Sanitize(m);
            string statusIcon = c.IsEnabled ? "✅ 啟用" : "❌ 停用";
            sb.AppendLine(CultureInfo.InvariantCulture,
                $"<tr><td>{statusIcon}</td><td>{WebUtility.HtmlEncode(c.Name)}</td><td>{WebUtility.HtmlEncode(c.Version)}</td><td>{WebUtility.HtmlEncode(c.MinecraftVersion)}</td><td>{WebUtility.HtmlEncode(c.LoaderType)}</td><td>{WebUtility.HtmlEncode(c.Author)}</td><td>{WebUtility.HtmlEncode(c.FileName)}</td><td>{WebUtility.HtmlEncode(c.Id)}</td><td>{WebUtility.HtmlEncode(c.FileSize)}</td><td>{WebUtility.HtmlEncode(c.ModifiedTime)}</td><td>{WebUtility.HtmlEncode(c.Description)}</td></tr>");
        }

        sb.AppendLine("</table></body></html>");
        return sb.ToString();
    }

    private static byte[] BuildXlsx(IReadOnlyList<ModListExportRow> rows)
    {
        var table = new List<IReadOnlyList<string>> { XlsxHeaders };
        foreach (ModListExportRow m in rows)
        {
            CleanRow c = Sanitize(m);
            table.Add([
                c.IsEnabled ? "是" : "否",
                SanitizeSpreadsheetFormula(c.Name),
                SanitizeSpreadsheetFormula(c.Version),
                SanitizeSpreadsheetFormula(c.MinecraftVersion),
                SanitizeSpreadsheetFormula(c.LoaderType),
                SanitizeSpreadsheetFormula(c.Author),
                SanitizeSpreadsheetFormula(c.FileName),
                SanitizeSpreadsheetFormula(c.Id),
                c.FileSize,
                c.ModifiedTime,
                SanitizeSpreadsheetFormula(c.Description),
            ]);
        }

        return OpenXmlSpreadsheetBuilder.BuildWorkbook(SheetName, table);
    }

    private static string SanitizeSpreadsheetFormula(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return string.Empty;
        }

        char first = value[0];
        if (first is '=' or '+' or '-' or '@' or '\t' or '\r')
        {
            return "'" + value;
        }

        return value;
    }

    private static string BuildText(IReadOnlyList<ModListExportRow> rows)
    {
        var sb = new StringBuilder();
        sb.AppendLine("# 模組清單");
        sb.AppendLine();

        foreach (ModListExportRow m in rows)
        {
            CleanRow c = Sanitize(m);
            string statusIcon = c.IsEnabled ? "✅" : "❌";
            string authorPart = !string.IsNullOrWhiteSpace(c.Author) ? $" - by {c.Author}" : string.Empty;
            sb.AppendLine(CultureInfo.InvariantCulture, $"{statusIcon} {c.Name} ({c.Version}){authorPart}");
        }

        return sb.ToString();
    }
}

internal sealed record ModJsonItem(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("enabled")] bool Enabled,
    [property: JsonPropertyName("minecraftVersion")] string MinecraftVersion,
    [property: JsonPropertyName("loaderType")] string LoaderType,
    [property: JsonPropertyName("author")] string Author,
    [property: JsonPropertyName("filename")] string FileName,
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("fileSize")] string FileSize,
    [property: JsonPropertyName("modifiedTime")] string ModifiedTime,
    [property: JsonPropertyName("description")] string Description);
