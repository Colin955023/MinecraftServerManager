using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

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
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ExportModListViewModel));

    /// <summary>
    /// 依指定格式匯出；使用者取消或匯出失敗時回傳 false
    /// </summary>
    public async Task<bool> ExportAsync(ModListExportFormat format)
    {
        (string extension, string filter) = Describe(format);
        string? path = await ui.PickSaveFileAsync("儲存模組列表", $"{serverName}_模組列表{extension}", filter).ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        try
        {
            await exporter.ExportAsync(rows, format, path).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            return false;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "模組列表匯出失敗：{Message}", ex.Message);
            await ui.ShowErrorAsync($"匯出失敗：{ex.Message}", "錯誤").ConfigureAwait(true);
            return false;
        }

        Logger.Information("模組列表已匯出: {Path}", path);

        // 匯出已成功；後續開啟確認若失敗只提示，不得誤報為匯出失敗
        try
        {
            if (await ui.ConfirmAsync($"已儲存：\n{path}\n\n是否要立即開啟匯出的檔案？", "匯出成功", UiMessageLevel.Information).ConfigureAwait(true) &&
                launcher is not null &&
                !launcher.OpenFile(path, isTrusted: true))
            {
                // 匯出檔案為程式內建產出內容，不需判斷是否拒絕開啟
                ui.ShowToast($"無法開啟檔案：{path}", "開啟失敗", ToastType.Warning);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "開啟匯出檔案流程失敗：{Message}", ex.Message);
            ui.ShowToast($"檔案已匯出，但開啟時發生錯誤：{ex.Message}", "開啟失敗", ToastType.Warning);
        }

        return true;
    }

    private static (string Extension, string Filter) Describe(ModListExportFormat format) => format switch
    {
        ModListExportFormat.Json => (".json", "JSON 檔案 (*.json)|*.json"),
        ModListExportFormat.Html => (".html", "HTML 網頁 (*.html)|*.html"),
        ModListExportFormat.Xlsx => (".xlsx", "Excel 工作表 (*.xlsx)|*.xlsx"),
        _ => (".txt", "純文字檔案 (*.txt)|*.txt"),
    };
}
