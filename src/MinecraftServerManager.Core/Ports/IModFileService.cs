namespace MinecraftServerManager.Core.Ports;

/// <summary>呈現層使用之模組檔案路徑解析、暫存清理與下載來源判定抽象介面</summary>
public interface IModFileService
{
    /// <summary>判斷下載網址是否為官方 Modrinth CDN</summary>
    public bool IsOfficialModrinthSource(string? url);

    /// <summary>清理伺服器 mods 目錄下的安裝暫存資料</summary>
    public void CleanupStagingDirectory(string serverPath);

    /// <summary>確保伺服器 mods 目錄存在並回傳其路徑</summary>
    public string EnsureModsDirectory(string serverPath);

    /// <summary>解析模組實體檔案路徑（含停用檔），找不到時回傳 mods 目錄</summary>
    public string ResolveModFilePath(string serverPath, string fileName);

    /// <summary>於伺服器目錄邊界內刪除指定模組檔案及其停用檔</summary>
    public void DeleteModFileVariants(string serverPath, string fileName);
}
