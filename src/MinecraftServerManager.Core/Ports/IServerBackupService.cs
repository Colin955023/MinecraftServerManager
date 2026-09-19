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
/// 伺服器備份與還原管理抽象介面
/// </summary>
public interface IServerBackupService
{
    /// <summary>
    /// 列出指定伺服器的所有備份檔案
    /// </summary>
    public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(string serverName, CancellationToken cancellationToken = default);

    /// <summary>
    /// 為指定伺服器建立新備份
    /// </summary>
    public Task<ServerBackupInfo> CreateBackupAsync(string serverName, string? comment = null, CancellationToken cancellationToken = default);

    /// <summary>
    /// 從備份還原伺服器檔案
    /// </summary>
    public Task<bool> RestoreBackupAsync(string serverName, string backupFileName, CancellationToken cancellationToken = default);

    /// <summary>
    /// 刪除指定的備份檔案
    /// </summary>
    public Task<bool> DeleteBackupAsync(string serverName, string backupFileName, CancellationToken cancellationToken = default);
}
