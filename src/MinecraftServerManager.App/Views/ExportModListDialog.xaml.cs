using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using Microsoft.Win32;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ExportModListDialog : Window
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    private static readonly string[] ModListXlsxHeaders = ["啟用狀態", "模組名稱", "版本", "作者", "檔案名稱", "模組ID", "描述"];
    private readonly IReadOnlyList<LocalModRowItem> _mods;
    private readonly string _serverName;

    public ExportModListDialog(string serverName, IReadOnlyList<LocalModRowItem> mods)
    {
        InitializeComponent();
        _serverName = serverName;
        _mods = mods;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void Export_Click(object sender, RoutedEventArgs e)
    {
        string extension = ".txt";
        string filter = "純文字檔案 (*.txt)|*.txt";
        if (JsonRadio.IsChecked == true)
        {
            extension = ".json";
            filter = "JSON 檔案 (*.json)|*.json";
        }
        else if (HtmlRadio.IsChecked == true)
        {
            extension = ".html";
            filter = "HTML 網頁 (*.html)|*.html";
        }
        else if (XlsxRadio.IsChecked == true)
        {
            extension = ".xlsx";
            filter = "Excel 工作表 (*.xlsx)|*.xlsx";
        }

        SaveFileDialog saveDialog = new()
        {
            Title = "儲存模組清單",
            FileName = $"{_serverName}{extension}",
            Filter = filter
        };

        if (saveDialog.ShowDialog(this) != true)
        {
            return;
        }

        try
        {
            WriteModListFile(saveDialog.FileName, extension);

            MessageBoxResult ask = MessageBox.Show(
                this,
                $"已成功匯出至：\n{saveDialog.FileName}\n\n是否要立即開啟此檔案？",
                "匯出完成",
                MessageBoxButton.YesNo,
                MessageBoxImage.Information);

            if (ask == MessageBoxResult.Yes)
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = saveDialog.FileName,
                        UseShellExecute = true
                    });
                }
                catch
                {
                    // 忽略外部開啟例外
                }
            }

            DialogResult = true;
            Close();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"匯出失敗：{ex.Message}", "錯誤", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void WriteModListFile(string filePath, string extension)
    {
        switch (extension.ToLowerInvariant())
        {
            case ".json":
                var items = _mods.Select(m => new
                {
                    name = m.Name,
                    version = m.Version,
                    enabled = m.IsEnabled,
                    author = m.Author == "-" ? string.Empty : m.Author,
                    filename = m.FileName,
                    description = m.Description,
                    id = m.Id
                });
                string json = JsonSerializer.Serialize(items, JsonOptions);
                File.WriteAllText(filePath, json, Encoding.UTF8);
                break;

            case ".html":
                StringBuilder sbHtml = new();
                sbHtml.AppendLine("<!DOCTYPE html>");
                sbHtml.AppendLine("<html lang=\"zh-TW\">");
                sbHtml.AppendLine("<head><meta charset=\"UTF-8\"><title>模組列表</title>");
                sbHtml.AppendLine("<style>table{border-collapse:collapse;}th,td{border:1px solid silver;padding:6px;}th{background:whitesmoke;}</style>");
                sbHtml.AppendLine("</head><body>");
                sbHtml.AppendLine("<h2>模組列表</h2>");
                sbHtml.AppendLine("<table>");
                sbHtml.AppendLine("<tr><th>啟用</th><th>名稱</th><th>版本</th><th>作者</th><th>檔案名稱</th><th>模組ID</th><th>描述</th></tr>");
                foreach (LocalModRowItem m in _mods)
                {
                    string statusIcon = m.IsEnabled ? "✅" : "❌";
                    string author = m.Author == "-" ? string.Empty : m.Author;
                    sbHtml.AppendLine(CultureInfo.InvariantCulture, $"<tr><td>{statusIcon}</td><td>{System.Net.WebUtility.HtmlEncode(m.Name)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Version)}</td><td>{System.Net.WebUtility.HtmlEncode(author)}</td><td>{System.Net.WebUtility.HtmlEncode(m.FileName)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Id)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Description)}</td></tr>");
                }
                sbHtml.AppendLine("</table></body></html>");
                File.WriteAllText(filePath, sbHtml.ToString(), Encoding.UTF8);
                break;

            case ".xlsx":
                var rows = new List<IReadOnlyList<string>>
                {
                    ModListXlsxHeaders
                };
                foreach (LocalModRowItem m in _mods)
                {
                    string status = m.IsEnabled ? "是" : "否";
                    string author = m.Author == "-" ? string.Empty : m.Author;
                    rows.Add([status, m.Name, m.Version, author, m.FileName, m.Id, m.Description]);
                }
                byte[] xlsxBytes = Infrastructure.Utilities.OpenXmlSpreadsheetBuilder.BuildWorkbook("模組列表", rows);
                File.WriteAllBytes(filePath, xlsxBytes);
                break;

            case ".txt":
            default:
                StringBuilder sbTxt = new();
                sbTxt.AppendLine("# 模組列表");
                sbTxt.AppendLine();
                foreach (LocalModRowItem m in _mods)
                {
                    string statusIcon = m.IsEnabled ? "✅" : "❌";
                    string author = m.Author == "-" ? string.Empty : m.Author;
                    string authorPart = !string.IsNullOrWhiteSpace(author) ? $" - by {author}" : string.Empty;
                    sbTxt.AppendLine(CultureInfo.InvariantCulture, $"{statusIcon} {m.Name} ({m.Version}){authorPart}");
                }
                File.WriteAllText(filePath, sbTxt.ToString(), Encoding.UTF8);
                break;
        }
    }
}
