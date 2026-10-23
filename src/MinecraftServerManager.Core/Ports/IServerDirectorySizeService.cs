namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器目錄大小計算服務合約。
/// 統一負責伺服器本體容量計算與快取管理（嚴格排除備份目錄）。
/// </summary>
public interface IServerDirectorySizeService
{
    /// <summary>
    /// 計算伺服器本體目錄大小（以位元組為單位），排除備份等外部檔案
    /// </summary>
    public Task<long> CalculateServerSizeAsync(string serverPath, CancellationToken cancellationToken = default);

    /// <summary>
    /// 格式化位元組為人類易讀格式（如 1.25 GB）
    /// </summary>
    public string FormatServerSize(long bytes);

    /// <summary>
    /// 使特定伺服器之容量快取失效（例如備份完成、伺服器停止或手動重新整理時呼叫）
    /// </summary>
    public void InvalidateCache(string serverPath);

    /// <summary>
    /// 清除所有快取
    /// </summary>
    public void ClearAllCache();
}
