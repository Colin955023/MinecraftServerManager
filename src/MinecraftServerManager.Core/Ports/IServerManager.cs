using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器 CRUD、建立與匯入管理抽象介面
/// </summary>
public interface IServerManager
{
    /// <summary>
    /// 取得所有已登錄之伺服器設定清單
    /// </summary>
    public Task<IReadOnlyList<ServerConfig>> GetAllServersAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// 依名稱取得指定伺服器設定
    /// </summary>
    public Task<ServerConfig?> GetServerAsync(string name, CancellationToken cancellationToken = default);

    /// <summary>
    /// 依建立計畫建立伺服器（支援交易回滾）
    /// </summary>
    public Task<ServerCreationResult> CreateServerAsync(ServerCreationPlan plan, CancellationToken cancellationToken = default);

    /// <summary>
    /// 刪除指定伺服器（支援兩階段安全標記與復原）
    /// </summary>
    public Task<ServerOperationResult> DeleteServerAsync(string name, CancellationToken cancellationToken = default);

    /// <summary>
    /// 更新已登錄伺服器設定
    /// </summary>
    public Task<ServerOperationResult> UpdateServerAsync(ServerConfig config, CancellationToken cancellationToken = default);

    /// <summary>
    /// 匯入外部伺服器目錄
    /// </summary>
    public Task<ServerImportResult> ImportServerAsync(
        string sourceDirectory,
        string targetName,
        ImportTransferMode mode = ImportTransferMode.Copy,
        CancellationToken cancellationToken = default);
}
