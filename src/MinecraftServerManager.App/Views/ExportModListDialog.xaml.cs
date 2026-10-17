using System.Windows;
using Microsoft.Win32;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 模組列表匯出對話方塊（僅負責選擇格式與檔案路徑，實際匯出交由 <see cref="IModListExporter"/>）
/// </summary>
public partial class ExportModListDialog : Window
{
    private readonly IReadOnlyList<ModListExportRow> _rows;
    private readonly string _serverName;
    private readonly IModListExporter _exporter;
    private readonly IExternalLauncher? _launcher;
    private readonly IUiService? _ui;

    public ExportModListDialog(
        string serverName,
        IReadOnlyList<ModListExportRow> rows,
        IModListExporter exporter,
        IExternalLauncher? launcher,
        IUiService? ui = null)
    {
        InitializeComponent();
        _serverName = serverName;
        _rows = rows;
        _exporter = exporter;
        _launcher = launcher;
        _ui = ui;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        (ModListExportFormat format, string extension, string filter) = GetSelectedFormat();

        var saveDialog = new SaveFileDialog
        {
            Title = "儲存模組列表",
            FileName = $"{_serverName}_模組列表{extension}",
            Filter = filter
        };

        if (saveDialog.ShowDialog(this) != true)
        {
            return;
        }

        try
        {
            await _exporter.ExportAsync(_rows, format, saveDialog.FileName).ConfigureAwait(true);

            bool open = _ui is not null
                ? _ui.Confirm($"已儲存：\n{saveDialog.FileName}\n\n是否要立即開啟匯出的檔案？", "匯出成功", UiMessageLevel.Information)
                : MessageBox.Show(this, $"已儲存：\n{saveDialog.FileName}\n\n是否要立即開啟匯出的檔案？", "匯出成功", MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes;

            if (open)
            {
                // 匯出檔案為程式內建產出內容，不需判斷是否拒絕開啟
                _launcher?.OpenFile(saveDialog.FileName, isTrusted: true);
            }

            DialogResult = true;
            Close();
        }
        catch (Exception ex)
        {
            if (_ui is not null)
            {
                _ui.ShowError($"匯出失敗：{ex.Message}", "錯誤");
            }
            else
            {
                MessageBox.Show(this, $"匯出失敗：{ex.Message}", "錯誤", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
    }

    private (ModListExportFormat Format, string Extension, string Filter) GetSelectedFormat()
    {
        if (JsonRadio.IsChecked == true)
        {
            return (ModListExportFormat.Json, ".json", "JSON 檔案 (*.json)|*.json");
        }

        if (HtmlRadio.IsChecked == true)
        {
            return (ModListExportFormat.Html, ".html", "HTML 網頁 (*.html)|*.html");
        }

        if (XlsxRadio.IsChecked == true)
        {
            return (ModListExportFormat.Xlsx, ".xlsx", "Excel 工作表 (*.xlsx)|*.xlsx");
        }

        return (ModListExportFormat.Text, ".txt", "純文字檔案 (*.txt)|*.txt");
    }
}
