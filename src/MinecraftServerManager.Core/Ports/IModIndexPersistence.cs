namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 模組快取索引持久化管理抽象介面
/// </summary>
public interface IModIndexPersistence
{
    /// <summary>
    /// 讀取已快取的模組中繼資料
    /// </summary>
    public IReadOnlyDictionary<string, string>? GetCachedMetadata(string fileName);

    /// <summary>
    /// 保存模組中繼資料至快取
    /// </summary>
    public void CacheMetadata(string fileName, IReadOnlyDictionary<string, string> metadata);

    /// <summary>
    /// 讀取已快取的檔案雜湊值
    /// </summary>
    public string? GetCachedHash(string fileName, string algorithm);

    /// <summary>
    /// 保存檔案雜湊值至快取
    /// </summary>
    public void CacheHash(string fileName, string algorithm, string hash);

    /// <summary>
    /// 標記特定檔案存在問題（例如損毀或 IO 異常）
    /// </summary>
    public void MarkIssue(string fileName, string reason);

    /// <summary>
    /// 清除快取索引
    /// </summary>
    public void ClearIndex();

    /// <summary>
    /// 清理不存在之過期索引項目
    /// </summary>
    public void CleanupStaleEntries(IEnumerable<string> existingFileNames);

    /// <summary>
    /// 將髒資料原子寫入硬碟
    /// </summary>
    public void Flush();
}
