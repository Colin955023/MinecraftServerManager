namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器備份檔案資訊</summary>
public sealed record ServerBackupInfo(
    string FileName,
    string FullPath,
    long SizeBytes,
    DateTimeOffset CreatedAt);

/// <summary>備份進度回報資訊</summary>
public sealed record ServerBackupProgressReport(
    int PercentCompleted,
    string CurrentFile,
    long ProcessedBytes,
    long TotalBytes);

/// <summary>外部備份資料夾狀態</summary>
public enum ServerBackupSummaryStatus
{
    NotConfigured,
    DirectoryMissing,
    NoBackups,
    HasBackups,
    ReadFailed,
}

/// <summary>外部備份資料夾摘要（備份數量與最新備份時間）</summary>
public sealed record ServerBackupSummary(
    ServerBackupSummaryStatus Status,
    int Count = 0,
    DateTimeOffset? LatestWriteTime = null);

/// <summary>伺服器備份與還原管理介面</summary>
public interface IServerBackupService
{
    /// <summary>列出指定伺服器的所有備份檔案</summary>
    public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(
        string serverName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default);

    /// <summary>為指定伺服器建立新備份（支援自訂備份檔案存放路徑與進度回報）</summary>
    public Task<ServerBackupInfo> CreateBackupAsync(
        string serverName,
        string? destinationPath = null,
        string? comment = null,
        IProgress<ServerBackupProgressReport>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>從備份還原伺服器檔案（支援進度回報）</summary>
    public Task<bool> RestoreBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        IProgress<ServerBackupProgressReport>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>刪除指定的備份檔案</summary>
    public Task<bool> DeleteBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default);

    /// <summary>取得外部備份資料夾內指定伺服器的備份摘要</summary>
    public Task<ServerBackupSummary> GetBackupSummaryAsync(string serverName, string? backupDirectory, CancellationToken cancellationToken = default);

    /// <summary>驗證備份目的地；合法回傳 null，否則回傳阻擋訊息</summary>
    public Task<string?> ValidateBackupDestinationAsync(string destinationPath, CancellationToken cancellationToken = default);

    /// <summary>建立備份目的資料夾並產生帶時間戳記的備份檔案完整路徑</summary>
    public Task<string> PrepareBackupFilePathAsync(string serverName, string destinationDirectory, CancellationToken cancellationToken = default);
}
