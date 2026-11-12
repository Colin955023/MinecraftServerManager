using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組清單匯出流程：選擇儲存位置、執行匯出並詢問是否開啟檔案；所有互動皆經由 <see cref="IUiService"/></summary>
public sealed class ExportModListViewModel(
    string serverName,
    IReadOnlyList<ModListExportRow> rows,
    IModListExporter exporter,
    IExternalLauncher launcher,
    IUiService ui)
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ExportModListViewModel));

    /// <summary>依指定格式匯出；使用者取消或匯出失敗時回傳 false</summary>
    public async Task<bool> ExportAsync(ModListExportFormat format)
    {
        FileTypeChoice fileType = Describe(format);
        string? path = await ui.PickSaveFileAsync("儲存模組清單", $"{serverName}_模組清單{fileType.Extension}", fileType).ConfigureAwait(true);
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
            Logger.Error(ex, "模組清單匯出失敗");
            await ui.ShowErrorAsync($"匯出失敗：{ex.Message}", "錯誤").ConfigureAwait(true);
            return false;
        }

        Logger.Information("模組清單已匯出: {Path}", path);

        // 匯出已成功；後續開啟確認若失敗只提示，不得誤報為匯出失敗
        try
        {
            if (await ui.ConfirmAsync($"已儲存：\n{path}\n\n是否要立即開啟匯出的檔案？", "匯出成功", UiMessageLevel.Information).ConfigureAwait(true) &&
                !launcher.OpenFile(path, isTrusted: true))
            {
                // 匯出檔案為程式內建產出內容，不需判斷是否拒絕開啟
                ui.ShowNotification($"無法開啟檔案：{path}", "開啟失敗", NotificationType.Warning);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "開啟匯出檔案流程失敗");
            ui.ShowNotification($"檔案已匯出，但開啟時發生錯誤：{ex.Message}", "開啟失敗", NotificationType.Warning);
        }

        return true;
    }

    private static FileTypeChoice Describe(ModListExportFormat format) => format switch
    {
        ModListExportFormat.Json => FileTypeChoice.Json,
        ModListExportFormat.Html => FileTypeChoice.Html,
        ModListExportFormat.Xlsx => FileTypeChoice.Xlsx,
        _ => FileTypeChoice.Text,
    };
}
