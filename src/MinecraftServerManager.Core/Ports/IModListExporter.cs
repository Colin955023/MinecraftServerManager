using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>模組清單匯出服務契約</summary>
public interface IModListExporter
{
    /// <summary>依指定格式將模組清單寫入檔案</summary>
    public Task ExportAsync(
        IReadOnlyList<ModListExportRow> rows,
        ModListExportFormat format,
        string filePath,
        CancellationToken cancellationToken = default);
}
