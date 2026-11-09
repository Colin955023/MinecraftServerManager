namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 呈現層使用之本機檔案系統存在性檢查與目錄建立抽象介面
/// </summary>
public interface ILocalFileSystem
{
    /// <summary>
    /// 檢查檔案是否存在
    /// </summary>
    public bool FileExists(string? path);

    /// <summary>
    /// 檢查目錄是否存在
    /// </summary>
    public bool DirectoryExists(string? path);

    /// <summary>
    /// 建立目錄（已存在時不做任何事）
    /// </summary>
    public void CreateDirectory(string path);

    /// <summary>
    /// 取得目錄最後修改時間；目錄不存在時回傳 null
    /// </summary>
    public DateTime? GetDirectoryLastWriteTime(string path);
}
