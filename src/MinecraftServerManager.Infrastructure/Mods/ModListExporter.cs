using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組列表匯出實作（純文字、JSON、HTML、XLSX），內容組裝與檔案寫入皆於背景執行緒完成
/// </summary>
public sealed class ModListExporter : IModListExporter
{
    private const string EmptyPlaceholder = "-";
    private const string SheetName = "模組列表";
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private static readonly string[] XlsxHeaders =
        ["啟用狀態", "模組名稱", "版本", "Minecraft版本", "載入器", "作者", "檔案名稱", "模組ID", "檔案大小", "修改時間", "描述"];

    /// <inheritdoc />
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
            await File.WriteAllBytesAsync(filePath, workbook, cancellationToken).ConfigureAwait(false);
            return;
        }

        string content = await Task.Run(() => format switch
        {
            ModListExportFormat.Json => BuildJson(rows),
            ModListExportFormat.Html => BuildHtml(rows),
            _ => BuildText(rows),
        }, cancellationToken).ConfigureAwait(false);

        await File.WriteAllTextAsync(filePath, content, Encoding.UTF8, cancellationToken).ConfigureAwait(false);
    }

    private static string Clean(string value) => value == EmptyPlaceholder ? string.Empty : value;

    private static string Encode(string value) => WebUtility.HtmlEncode(value);

    private static string BuildJson(IReadOnlyList<ModListExportRow> rows)
    {
        List<ModJsonItem> items = [.. rows
            .Select(m => new ModJsonItem(
                Name: m.Name,
                Version: m.Version,
                Enabled: m.IsEnabled,
                MinecraftVersion: Clean(m.MinecraftVersion),
                LoaderType: Clean(m.LoaderType),
                Author: Clean(m.Author),
                FileName: m.FileName,
                Id: m.Id,
                FileSize: Clean(m.FileSize),
                ModifiedTime: Clean(m.ModifiedTime),
                Description: m.Description))];

        return JsonSerializer.Serialize(items, JsonOptions);
    }

    private static string BuildHtml(IReadOnlyList<ModListExportRow> rows)
    {
        var sb = new StringBuilder();
        sb.AppendLine("<!DOCTYPE html>");
        sb.AppendLine("<html lang=\"zh-TW\">");
        sb.AppendLine("<head><meta charset=\"UTF-8\"><title>模組列表</title>");
        sb.AppendLine("<style>table{border-collapse:collapse;width:100%;}th,td{border:1px solid silver;padding:6px;text-align:left;}th{background:whitesmoke;}</style>");
        sb.AppendLine("</head><body>");
        sb.AppendLine("<h2>模組列表</h2>");
        sb.AppendLine("<table>");
        sb.AppendLine("<tr><th>啟用狀態</th><th>模組名稱</th><th>版本</th><th>MC版本</th><th>載入器</th><th>作者</th><th>檔案名稱</th><th>模組ID</th><th>檔案大小</th><th>修改時間</th><th>描述</th></tr>");

        foreach (ModListExportRow m in rows)
        {
            string statusIcon = m.IsEnabled ? "✅ 啟用" : "❌ 停用";
            sb.AppendLine(CultureInfo.InvariantCulture,
                $"<tr><td>{statusIcon}</td><td>{Encode(m.Name)}</td><td>{Encode(m.Version)}</td><td>{Encode(Clean(m.MinecraftVersion))}</td><td>{Encode(Clean(m.LoaderType))}</td><td>{Encode(Clean(m.Author))}</td><td>{Encode(m.FileName)}</td><td>{Encode(m.Id)}</td><td>{Encode(Clean(m.FileSize))}</td><td>{Encode(Clean(m.ModifiedTime))}</td><td>{Encode(m.Description)}</td></tr>");
        }

        sb.AppendLine("</table></body></html>");
        return sb.ToString();
    }

    private static byte[] BuildXlsx(IReadOnlyList<ModListExportRow> rows)
    {
        var table = new List<IReadOnlyList<string>> { XlsxHeaders };
        foreach (ModListExportRow m in rows)
        {
            table.Add([
                m.IsEnabled ? "是" : "否",
                m.Name,
                m.Version,
                Clean(m.MinecraftVersion),
                Clean(m.LoaderType),
                Clean(m.Author),
                m.FileName,
                m.Id,
                Clean(m.FileSize),
                Clean(m.ModifiedTime),
                m.Description,
            ]);
        }

        return OpenXmlSpreadsheetBuilder.BuildWorkbook(SheetName, table);
    }

    private static string BuildText(IReadOnlyList<ModListExportRow> rows)
    {
        var sb = new StringBuilder();
        sb.AppendLine("# 模組列表");
        sb.AppendLine();

        foreach (ModListExportRow m in rows)
        {
            string statusIcon = m.IsEnabled ? "✅" : "❌";
            string author = Clean(m.Author);
            string authorPart = !string.IsNullOrWhiteSpace(author) ? $" - by {author}" : string.Empty;
            sb.AppendLine(CultureInfo.InvariantCulture, $"{statusIcon} {m.Name} ({m.Version}){authorPart}");
        }

        return sb.ToString();
    }

    private sealed record ModJsonItem(
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
}
