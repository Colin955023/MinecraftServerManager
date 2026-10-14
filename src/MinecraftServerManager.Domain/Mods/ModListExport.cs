namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 模組列表匯出格式
/// </summary>
public enum ModListExportFormat
{
    Text,
    Json,
    Html,
    Xlsx,
}

/// <summary>
/// 模組列表匯出的單列資料，不含任何 UI 型別
/// </summary>
public sealed record ModListExportRow(
    string Id,
    string Name,
    string Version,
    string FileName,
    string FileSize,
    string Author,
    string LoaderType,
    string MinecraftVersion,
    string ModifiedTime,
    string Description,
    bool IsEnabled);
