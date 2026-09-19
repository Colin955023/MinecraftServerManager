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
            FileName = $"mods_{_serverName}_{DateTime.Now:yyyyMMdd_HHmmss}{extension}",
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
                    id = m.Id,
                    name = m.Name,
                    version = m.Version,
                    fileName = m.FileName,
                    fileSize = m.FileSize,
                    isEnabled = m.IsEnabled
                });
                string json = JsonSerializer.Serialize(items, JsonOptions);
                File.WriteAllText(filePath, json, Encoding.UTF8);
                break;

            case ".html":
                StringBuilder sbHtml = new();
                sbHtml.AppendLine("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>模組清單 - " + _serverName + "</title>");
                sbHtml.AppendLine("<style>body{font-family:sans-serif;margin:24px;} table{border-collapse:collapse;width:100%;} th,td{border:1px solid #ddd;padding:8px;text-align:left;} th{background-color:#4CAF50;color:white;} tr:nth-child(even){background-color:#f9f9f9;}</style>");
                sbHtml.AppendLine("</head><body>");
                sbHtml.AppendLine(CultureInfo.InvariantCulture, $"<h1>模組清單 — {_serverName}</h1>");
                sbHtml.AppendLine(CultureInfo.InvariantCulture, $"<p>匯出時間：{DateTime.Now:yyyy-MM-dd HH:mm:ss}，總計 {_mods.Count} 個模組</p>");
                sbHtml.AppendLine("<table><thead><tr><th>狀態</th><th>模組名稱</th><th>版本</th><th>檔案名稱</th><th>大小</th></tr></thead><tbody>");
                foreach (LocalModRowItem m in _mods)
                {
                    string status = m.IsEnabled ? "啟用" : "停用";
                    sbHtml.AppendLine(CultureInfo.InvariantCulture, $"<tr><td>{status}</td><td>{System.Net.WebUtility.HtmlEncode(m.Name)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Version)}</td><td>{System.Net.WebUtility.HtmlEncode(m.FileName)}</td><td>{m.FileSize}</td></tr>");
                }
                sbHtml.AppendLine("</tbody></table></body></html>");
                File.WriteAllText(filePath, sbHtml.ToString(), Encoding.UTF8);
                break;

            case ".xlsx":
            case ".txt":
            default:
                StringBuilder sbTxt = new();
                sbTxt.AppendLine(CultureInfo.InvariantCulture, $"=== 模組清單 — {_serverName} ===");
                sbTxt.AppendLine(CultureInfo.InvariantCulture, $"匯出時間：{DateTime.Now:yyyy-MM-dd HH:mm:ss}");
                sbTxt.AppendLine(CultureInfo.InvariantCulture, $"模組總數：{_mods.Count} 個");
                sbTxt.AppendLine(new string('-', 80));
                foreach (LocalModRowItem m in _mods)
                {
                    string status = m.IsEnabled ? "[啟用]" : "[停用]";
                    sbTxt.AppendLine(CultureInfo.InvariantCulture, $"{status} {m.Name} (版本: {m.Version}) - {m.FileName} ({m.FileSize})");
                }
                File.WriteAllText(filePath, sbTxt.ToString(), Encoding.UTF8);
                break;
        }
    }
}
