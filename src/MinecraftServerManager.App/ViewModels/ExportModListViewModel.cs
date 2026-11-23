using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組清單匯出流程：選擇位置、匯出並詢問是否開啟</summary>
public sealed class ExportModListViewModel
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ExportModListViewModel));
    private readonly string _serverName;
    private readonly IReadOnlyList<ModListExportRow> _rows;
    private readonly IModListExporter _exporter;
    private readonly IExternalLauncher _launcher;
    private readonly IUiService _ui;

    public ExportModListViewModel(
        string serverName,
        IReadOnlyList<ModListExportRow> rows,
        IModListExporter exporter,
        IExternalLauncher launcher,
        IUiService ui)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentNullException.ThrowIfNull(rows);
        ArgumentNullException.ThrowIfNull(exporter);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(ui);

        _serverName = serverName;
        _rows = rows;
        _exporter = exporter;
        _launcher = launcher;
        _ui = ui;
    }

    /// <summary>顯示格式選擇對話方塊並執行匯出；取消儲存或匯出失敗時重新顯示格式選擇</summary>
    public async Task RunAsync()
    {
        while (await _ui.ShowExportModListAsync() is { } format)
        {
            if (await ExportAsync(format))
            {
                break;
            }
        }
    }

    /// <summary>依指定格式匯出；使用者取消或匯出失敗時回傳 false</summary>
    public async Task<bool> ExportAsync(ModListExportFormat format)
    {
        FileTypeChoice fileType = Describe(format);
        string? path = await _ui.PickSaveFileAsync("儲存模組清單", $"{_serverName}_模組清單{fileType.Extension}", fileType);
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        try
        {
            await _exporter.ExportAsync(_rows, format, path);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("模組清單匯出已取消");
            return false;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "模組清單匯出失敗");
            await _ui.ShowErrorAsync($"匯出失敗：{ex.Message}", "匯出失敗");
            return false;
        }

        Logger.Information("模組清單已匯出：{Path}", path);

        // 匯出已成功；後續開啟確認若失敗只提示，不得誤報為匯出失敗
        try
        {
            if (await _ui.ConfirmAsync($"已儲存：\n{path}\n\n是否要立即開啟匯出的檔案？", "匯出成功", UiMessageLevel.Information))
            {
                // 匯出檔案為程式內建產出內容，不需判斷是否拒絕開啟
                _ui.OpenFileOrWarn(_launcher, path, isTrusted: true, title: "開啟失敗");
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "開啟匯出檔案流程失敗");
            _ui.ShowNotification($"檔案已匯出，但開啟時發生錯誤：{ex.Message}", "開啟失敗", NotificationType.Warning);
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
