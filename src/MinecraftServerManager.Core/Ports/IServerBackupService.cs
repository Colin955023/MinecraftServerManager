namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器備份檔案資訊
/// </summary>
public sealed record ServerBackupInfo(
    string FileName,
    string FullPath,
    long SizeBytes,
    DateTimeOffset CreatedAt);

/// <summary>
/// 備份進度回報資訊
/// </summary>
public sealed record ServerBackupProgressReport(
    int PercentCompleted,
    string CurrentFile,
    long ProcessedBytes,
    long TotalBytes);

/// <summary>
/// 伺服器備份與還原管理抽象介面
/// </summary>
public interface IServerBackupService
{
    /// <summary>
    /// 列出指定伺服器的所有備份檔案
    /// </summary>
    public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(
        string serverName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 為指定伺服器建立新備份（支援自訂備份檔案存放路徑與進度回報）
    /// </summary>
    public Task<ServerBackupInfo> CreateBackupAsync(
        string serverName,
        string? destinationPath = null,
        string? comment = null,
        IProgress<ServerBackupProgressReport>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 從備份還原伺服器檔案
    /// </summary>
    public Task<bool> RestoreBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 刪除指定的備份檔案
    /// </summary>
    public Task<bool> DeleteBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default);
}
