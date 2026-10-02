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
    public Task<ServerCreationResult> CreateServerAsync(
        ServerCreationPlan plan,
        IProgress<ServerCreationProgressReport>? progress = null,
        CancellationToken cancellationToken = default);

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
        IProgress<ServerImportProgressReport>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 掃描 servers 根目錄之一級子目錄，將符合伺服器結構但尚未註冊者自動加入註冊表
    /// </summary>
    public Task<ServerScanReport> ScanAndRegisterAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// 建立伺服器之五階段進度回報
/// </summary>
public sealed record ServerCreationProgressReport(
    ServerCreationPhase Phase,
    int PercentCompleted,
    string Message);

/// <summary>
/// 建立伺服器流程階段
/// </summary>
public enum ServerCreationPhase
{
    Validate,
    Stage,
    Artifact,
    LaunchScript,
    Commit,
}

/// <summary>
/// 偵測現有伺服器之分類統計報告
/// </summary>
public sealed record ServerScanReport(
    int AlreadyManaged,
    int NewlyAdded,
    int Skipped,
    IReadOnlyList<string> NewlyAddedNames);

/// <summary>
/// 伺服器匯入進度回報資料模型
/// </summary>
public sealed record ServerImportProgressReport(int Percentage, string StageText);
