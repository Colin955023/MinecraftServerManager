using MinecraftServerManager.Core.Mods;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 檔案選取器可選的單一檔案類型：所有選取器一律從下列預設集合挑選，建構子私有以避免各處自訂格式
/// </summary>
public sealed class FileTypeChoice
{
    private FileTypeChoice(string label, string extension)
    {
        Label = label;
        Extension = extension;
    }

    /// <summary>
    /// 顯示於選取器的類型名稱
    /// </summary>
    public string Label { get; }

    /// <summary>
    /// 含前導句點的副檔名（如 ".zip"）
    /// </summary>
    public string Extension { get; }

    /// <summary>伺服器 ZIP 壓縮檔</summary>
    public static FileTypeChoice Zip { get; } = new("ZIP 壓縮檔 (*.zip)", ".zip");

    /// <summary>Minecraft 模組檔案</summary>
    public static FileTypeChoice Jar { get; } = new("Minecraft 模組 (*.jar)", ModHelpers.JarExtension);

    /// <summary>Java 執行檔</summary>
    public static FileTypeChoice JavaExecutable { get; } = new("Java 執行檔 (*.exe)", ".exe");

    /// <summary>模組列表 JSON 匯出</summary>
    public static FileTypeChoice Json { get; } = new("JSON 檔案 (*.json)", ".json");

    /// <summary>模組列表 HTML 匯出</summary>
    public static FileTypeChoice Html { get; } = new("HTML 網頁 (*.html)", ".html");

    /// <summary>模組列表 Excel 匯出</summary>
    public static FileTypeChoice Xlsx { get; } = new("Excel 工作表 (*.xlsx)", ".xlsx");

    /// <summary>模組列表純文字匯出</summary>
    public static FileTypeChoice Text { get; } = new("純文字檔案 (*.txt)", ".txt");
}
