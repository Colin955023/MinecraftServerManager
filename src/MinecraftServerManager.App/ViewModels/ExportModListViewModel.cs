using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 模組列表匯出流程：選擇儲存位置、執行匯出並詢問是否開啟檔案；所有互動皆經由 <see cref="IUiService"/>
/// </summary>
public sealed class ExportModListViewModel(
    string serverName,
    IReadOnlyList<ModListExportRow> rows,
    IModListExporter exporter,
    IExternalLauncher? launcher,
    IUiService ui)
{
    /// <summary>
    /// 依指定格式匯出；使用者取消或匯出失敗時回傳 false
    /// </summary>
    public async Task<bool> ExportAsync(ModListExportFormat format)
    {
        (string extension, string filter) = Describe(format);
        string? path = ui.PickSaveFile("儲存模組列表", $"{serverName}_模組列表{extension}", filter);
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        try
        {
            await exporter.ExportAsync(rows, format, path).ConfigureAwait(true);

            if (ui.Confirm($"已儲存：\n{path}\n\n是否要立即開啟匯出的檔案？", "匯出成功", UiMessageLevel.Information))
            {
                // 匯出檔案為程式內建產出內容，不需判斷是否拒絕開啟
                launcher?.OpenFile(path, isTrusted: true);
            }

            return true;
        }
        catch (Exception ex)
        {
            ui.ShowError($"匯出失敗：{ex.Message}", "錯誤");
            return false;
        }
    }

    private static (string Extension, string Filter) Describe(ModListExportFormat format) => format switch
    {
        ModListExportFormat.Json => (".json", "JSON 檔案 (*.json)|*.json"),
        ModListExportFormat.Html => (".html", "HTML 網頁 (*.html)|*.html"),
        ModListExportFormat.Xlsx => (".xlsx", "Excel 工作表 (*.xlsx)|*.xlsx"),
        _ => (".txt", "純文字檔案 (*.txt)|*.txt"),
    };
}
