using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// server.properties 存取與原子更新抽象介面
/// </summary>
public interface IServerPropertiesStore
{
    /// <summary>
    /// 讀取伺服器屬性快照
    /// </summary>
    public Task<ServerPropertiesSnapshot> ReadAsync(
        string serverName,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 以指定預期版本原子更新伺服器屬性（防止並行衝突）
    /// </summary>
    public Task<ServerPropertiesUpdateResult> UpdateAsync(
        string serverName,
        IReadOnlyDictionary<string, string> patches,
        string expectedRevision,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 分析並遷移伺服器舊版屬性
    /// </summary>
    public Task<ServerPropertiesMigrationPlan> MigrateAsync(
        string serverName,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 取得指定伺服器 server.properties 實體檔案路徑
    /// </summary>
    public string GetPropertiesFilePath(string serverName);
}
