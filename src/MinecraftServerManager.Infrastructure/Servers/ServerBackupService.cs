using System.Globalization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器備份與交易式還原服務</summary>
public sealed class ServerBackupService : IServerBackupService
{
    private const int CleanupRetryCount = 3;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerBackupService));
    private static readonly TimeSpan CleanupRetryDelay = TimeSpan.FromMilliseconds(200);
    private static readonly TimeSpan ProgressReportInterval = TimeSpan.FromMilliseconds(100);

    private readonly string _resolvedServersRoot;
    private readonly Func<int> _retentionCountProvider;
    private readonly KeyedAsyncLock _serverGates = new();
    private readonly TimeProvider _timeProvider;

    public ServerBackupService(string serversRoot, Func<int> retentionCountProvider, TimeProvider timeProvider)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        ArgumentNullException.ThrowIfNull(retentionCountProvider);
        ArgumentNullException.ThrowIfNull(timeProvider);
        _timeProvider = timeProvider;
        _resolvedServersRoot = SafeFileSystem.ResolveStableDirectory(serversRoot);
        _retentionCountProvider = retentionCountProvider;
    }

    public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(
        string serverName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        cancellationToken.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(backupDirectory))
        {
            return Task.FromResult<IReadOnlyList<ServerBackupInfo>>([]);
        }

        return Task.Run(() => ListBackups(serverName, backupDirectory), cancellationToken);
    }

    private IReadOnlyList<ServerBackupInfo> ListBackups(string serverName, string backupDirectory)
    {
        string backupsDir = ResolveExternalBackupDirectory(backupDirectory);
        return !SafeFileSystem.DirectoryExists(backupsDir)
            ? []
            : [.. EnumerateServerBackups(serverName, backupsDir).OrderByDescending(static b => b.CreatedAt)];
    }

    public Task<ServerBackupSummary> GetBackupSummaryAsync(string serverName, string? backupDirectory, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        if (string.IsNullOrWhiteSpace(backupDirectory))
        {
            return Task.FromResult(new ServerBackupSummary(ServerBackupSummaryStatus.NotConfigured));
        }

        return Task.Run(() => GetBackupSummary(serverName, backupDirectory), cancellationToken);
    }

    private static ServerBackupSummary GetBackupSummary(string serverName, string backupDirectory)
    {
        try
        {
            if (!SafeFileSystem.DirectoryExists(backupDirectory))
            {
                return new ServerBackupSummary(ServerBackupSummaryStatus.DirectoryMissing);
            }

            int count = 0;
            DateTimeOffset? latestUtc = null;
            foreach (var backup in EnumerateServerBackups(serverName, backupDirectory))
            {
                count++;
                if (latestUtc is null || backup.CreatedAt > latestUtc)
                {
                    latestUtc = backup.CreatedAt;
                }
            }

            return count > 0
                ? new ServerBackupSummary(ServerBackupSummaryStatus.HasBackups, count, latestUtc?.ToLocalTime())
                : new ServerBackupSummary(ServerBackupSummaryStatus.NoBackups);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取備份清單失敗 ({Path})", backupDirectory);
            return new ServerBackupSummary(ServerBackupSummaryStatus.ReadFailed);
        }
    }

    private static IEnumerable<ServerBackupInfo> EnumerateServerBackups(string serverName, string backupDirectory)
    {
        foreach (var entry in SafeFileSystem.ListBoundedDirectory(backupDirectory, rejectReparse: false))
        {
            if (entry.IsDirectory || !entry.FullPath.EndsWith(ZipExtension, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string fileName = Path.GetFileName(entry.FullPath);
            if (IsBackupFileFor(serverName, fileName))
            {
                yield return new ServerBackupInfo(
                    FileName: fileName,
                    FullPath: entry.FullPath,
                    SizeBytes: entry.Length,
                    CreatedAt: new DateTimeOffset(DateTime.SpecifyKind(entry.LastWriteTimeUtc, DateTimeKind.Utc)));
            }
        }
    }

    public Task<string?> ValidateBackupDestinationAsync(string destinationPath, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(destinationPath))
        {
            return Task.FromResult<string?>("未指定備份路徑");
        }

        return Task.Run(() => ValidateBackupDestination(destinationPath), cancellationToken);
    }

    private string? ValidateBackupDestination(string destinationPath)
    {

        try
        {
            string targetDir = SafeFileSystem.FileExists(destinationPath) || destinationPath.EndsWith(ZipExtension, StringComparison.OrdinalIgnoreCase)
                ? (Path.GetDirectoryName(destinationPath) ?? destinationPath)
                : destinationPath;

            return IsInsideServersRoot(targetDir)
                ? "備份路徑不得位於伺服器存放目錄或其子目錄內，請重新選擇其他外部資料夾。"
                : null;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "路徑邊界解析失敗");
            return $"路徑解析失敗：{ex.Message}";
        }
    }

    public Task<string> PrepareBackupFilePathAsync(string serverName, string destinationDirectory, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(destinationDirectory);

        return Task.Run(() =>
        {
            SafeFileSystem.CreateDirectory(destinationDirectory);
            return Path.Combine(destinationDirectory, BuildBackupFileName(serverName, shortId: null));
        }, cancellationToken);
    }

    private const string BackupPrefix = "backup-";
    private const string ZipExtension = ".zip";
    private const string TimestampFormat = "yyyyMMdd-HHmmss";

    /// <summary>以本機時間產生備份檔名：<c>backup-{伺服器}-{時間戳記}[-{識別碼}].zip</c></summary>
    private string BuildBackupFileName(string serverName, string? shortId)
    {
        string timestamp = FormatLocalTimestamp();
        return shortId is null
            ? $"{BackupPrefix}{serverName}-{timestamp}{ZipExtension}"
            : $"{BackupPrefix}{serverName}-{timestamp}-{shortId}{ZipExtension}";
    }

    private string FormatLocalTimestamp() =>
        _timeProvider.GetLocalNow().ToString(TimestampFormat, CultureInfo.InvariantCulture);

    /// <summary>是否為指定伺服器的備份檔（名稱後須接時間戳記）</summary>
    internal static bool IsBackupFileFor(string serverName, string fileName)
    {
        ReadOnlySpan<char> file = fileName;
        ReadOnlySpan<char> name = serverName;
        return MatchesBackupName(file, BackupPrefix, name) || MatchesBackupName(file, default, name);
    }

    private static bool MatchesBackupName(ReadOnlySpan<char> fileName, ReadOnlySpan<char> prefix, ReadOnlySpan<char> serverName)
    {
        if (!fileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        ReadOnlySpan<char> rest = fileName[prefix.Length..];
        if (!rest.StartsWith(serverName, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        rest = rest[serverName.Length..];
        if (rest.Equals(ZipExtension, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        // 時間戳記格式：-yyyyMMdd-HHmmss，後接選用識別碼與 .zip
        const int stampLength = 1 + 8 + 1 + 6;
        return rest.Length >= stampLength + ZipExtension.Length
            && rest.EndsWith(ZipExtension, StringComparison.OrdinalIgnoreCase)
            && rest[0] == '-'
            && rest.Slice(1, 8).ContainsAnyExceptInRange('0', '9') is false
            && rest[9] == '-'
            && rest.Slice(10, 6).ContainsAnyExceptInRange('0', '9') is false;
    }

    public async Task<ServerBackupInfo> CreateBackupAsync(
        string serverName,
        string? destinationPath = null,
        string? comment = null,
        IProgress<ServerBackupProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        cancellationToken.ThrowIfCancellationRequested();

        string serverDir = GetServerDirectory(serverName);
        if (!SafeFileSystem.DirectoryExists(serverDir))
        {
            throw new DirectoryNotFoundException($"找不到伺服器目錄：{serverDir}");
        }

        if (string.IsNullOrWhiteSpace(destinationPath))
        {
            throw new InvalidOperationException("未指定備份目標路徑。備份必須存放於伺服器目錄以外之外部資料夾。");
        }

        if (IsInsideServersRoot(destinationPath))
        {
            throw new InvalidOperationException("備份路徑不得位於伺服器根目錄 (servers/) 或其子目錄內，請選擇其他儲存位置");
        }

        // 同伺服器的備份與還原互斥
        using var gate = await _serverGates.AcquireAsync(serverName, cancellationToken).ConfigureAwait(false);

        string backupFileName = BuildBackupFileName(serverName, Guid.NewGuid().ToString("N")[..6]);

        string backupDirectory;
        string backupFilePath;
        if (destinationPath.EndsWith(ZipExtension, StringComparison.OrdinalIgnoreCase))
        {
            backupFilePath = Path.GetFullPath(destinationPath);
            backupFileName = Path.GetFileName(backupFilePath);
            string? parentDir = Path.GetDirectoryName(backupFilePath);
            if (string.IsNullOrEmpty(parentDir))
            {
                throw new InvalidOperationException("無法解析備份檔案的父資料夾");
            }

            backupDirectory = ResolveExternalBackupDirectory(parentDir);
        }
        else
        {
            backupDirectory = ResolveExternalBackupDirectory(destinationPath);
            backupFilePath = Path.Combine(backupDirectory, backupFileName);
        }

        await Task.Run(() =>
        {
            List<FileSystemEntry> filesToBackup;
            try
            {
                var entries = SafeFileSystem.EnumerateBoundedTree(
                    serverDir,
                    rejectReparse: true,
                    // 只略過根目錄下的 logs、crash-reports 與 backups
                    pruneDirectory: (fullPath, name) =>
                        string.Equals(Path.GetDirectoryName(fullPath), serverDir, StringComparison.OrdinalIgnoreCase) &&
                        (name.Equals(ServerDefaults.LogsDirectoryName, StringComparison.OrdinalIgnoreCase) ||
                         name.Equals(ServerDefaults.CrashReportsDirectoryName, StringComparison.OrdinalIgnoreCase) ||
                         name.Equals(ServerDefaults.BackupsDirectoryName, StringComparison.OrdinalIgnoreCase)));

                filesToBackup = [.. entries
                    .Where(static e => !e.IsDirectory &&
                        !e.FullPath.EndsWith(AtomicFileWriter.TempFileExtension, StringComparison.OrdinalIgnoreCase) &&
                        !e.FullPath.EndsWith(".lock", StringComparison.OrdinalIgnoreCase))];
            }
            catch (SafeFileSystemException ex) when (ex.IsLimitExceeded)
            {
                throw new InvalidOperationException($"伺服器檔案數量或大小超過安全備份上限（安全上限：{SafeFileSystem.DefaultMaxEntries} 個項目或 128 GB）。請清理地圖快取或暫存檔案後重試。", ex);
            }

            long totalBytes = filesToBackup.Sum(static f => f.Length);
            long processedBytes = 0;
            var progressThrottle = new ProgressThrottle(ProgressReportInterval, _timeProvider);

            SafeZipArchive.WriteArchive(backupFilePath, writer =>
            {
                if (!string.IsNullOrWhiteSpace(comment))
                {
                    writer.SetComment(comment);
                }

                foreach (var entry in filesToBackup)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    string filePath = entry.FullPath;
                    string relativePath = Path.GetRelativePath(serverDir, filePath);
                    long writtenBytes = writer.WriteFile(relativePath, filePath);
                    processedBytes += writtenBytes;

                    if (progress is null)
                    {
                        continue;
                    }

                    // 大量小檔案時節流進度回報，避免灌爆 UI 執行緒
                    int percent = ProgressMapping.Map(processedBytes, totalBytes, 0, 100);
                    if (progressThrottle.ShouldReport(percent))
                    {
                        progress.Report(new ServerBackupProgressReport(
                            PercentCompleted: percent,
                            CurrentFile: relativePath,
                            ProcessedBytes: processedBytes,
                            TotalBytes: totalBytes));
                    }
                }

                progress?.Report(new ServerBackupProgressReport(
                    PercentCompleted: 100,
                    CurrentFile: string.Empty,
                    ProcessedBytes: totalBytes,
                    TotalBytes: totalBytes));
            });
        }, cancellationToken).ConfigureAwait(false);

        FileSystemMetadata fileInfo = SafeFileSystem.GetFileMetadata(backupFilePath);

        // 依備份保留政策自動清理最舊備份
        await PruneOldBackupsAsync(serverName, backupDirectory, cancellationToken).ConfigureAwait(false);

        return new ServerBackupInfo(
            FileName: fileInfo.Name,
            FullPath: fileInfo.FullPath,
            SizeBytes: fileInfo.Length,
            CreatedAt: fileInfo.LastWriteTimeUtc);
    }

    public async Task<bool> RestoreBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        IProgress<ServerBackupProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(backupFileName);
        cancellationToken.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(backupDirectory))
        {
            throw new InvalidOperationException("未指定備份資料夾路徑。備份必須位於伺服器目錄以外之外部資料夾。");
        }

        if (!string.Equals(Path.GetFileName(backupFileName), backupFileName, StringComparison.Ordinal)
            || !IsBackupFileFor(serverName, backupFileName))
        {
            Logger.Warning("拒絕還原非該伺服器之備份檔: {Server}: {FileName}", serverName, backupFileName);
            return false;
        }

        string serverDir = GetServerDirectory(serverName);
        string backupsDir = ResolveExternalBackupDirectory(backupDirectory);
        string backupFilePath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (!SafeFileSystem.FileExists(backupFilePath))
        {
            return false;
        }

        using var gate = await _serverGates.AcquireAsync(serverName, cancellationToken).ConfigureAwait(false);

        string stagingDir = Path.Combine(_resolvedServersRoot, $"{ServerDefaults.InternalPrefix}restore-staging-{Guid.NewGuid():N}");
        string rollbackDir = Path.Combine(_resolvedServersRoot, $"{ServerDefaults.InternalPrefix}restore-rollback-{Guid.NewGuid():N}");
        string preservedLogsDir = Path.Combine(_resolvedServersRoot, $"{ServerDefaults.InternalPrefix}restore-preserved-logs-{Guid.NewGuid():N}");
        bool hasPreservedLogs = false;
        bool snapshotCompleted = false;

        progress?.Report(new ServerBackupProgressReport(5, "正在暫存現場診斷記錄檔...", 0, 0));

        return await Task.Run(() =>
        {
            try
            {
                // 階段零：暫存 logs 與 crash-reports
                if (SafeFileSystem.DirectoryExists(serverDir))
                {
                    SafeFileSystem.RemoveReadOnlyAttributesRecursive(serverDir);
                    PreserveLiveDiagnostics(serverDir, preservedLogsDir, cancellationToken);
                    hasPreservedLogs = SafeFileSystem.DirectoryExists(preservedLogsDir) && !SafeFileSystem.IsDirectoryEmpty(preservedLogsDir);
                }

                // 階段一：在暫存 staging 目錄解壓縮並驗證完整性
                SafeFileSystem.CreateDirectory(stagingDir);
                progress?.Report(new ServerBackupProgressReport(10, "正在解壓縮備份檔案...", 0, 0));
                var extractThrottle = new ProgressThrottle(ProgressReportInterval, _timeProvider);
                SafeZipArchive.Extract(backupFilePath, stagingDir, (extracted, total) =>
                {
                    if (progress is null)
                    {
                        return;
                    }

                    int pct = ProgressMapping.Map(extracted, total, 10, 60, unknown: 35);
                    if (extractThrottle.ShouldReport(pct))
                    {
                        progress.Report(new ServerBackupProgressReport(pct, $"正在解壓縮檔案 ({pct}%)...", extracted, total));
                    }
                }, cancellationToken);
                SafeFileSystem.RemoveReadOnlyAttributesRecursive(stagingDir);

                // 階段二：建立既有伺服器檔案之 rollback 快照
                progress?.Report(new ServerBackupProgressReport(65, "正在建立伺服器現況快照...", 0, 0));
                SafeFileSystem.CreateDirectory(rollbackDir);
                string legacyBackupsDir = Path.Combine(serverDir, ServerDefaults.BackupsDirectoryName);
                SafeFileSystem.MoveChildren(
                    serverDir,
                    rollbackDir,
                    // 保留歷史 backups 目錄不移動
                    skip: entry => string.Equals(entry.FullPath, legacyBackupsDir, StringComparison.OrdinalIgnoreCase),
                    beforeMove: (entry, _) => SafeFileSystem.ClearReadOnlyAttribute(entry.FullPath));
                snapshotCompleted = true;

                // 階段三：將 staging 中的還原內容搬移至伺服器目錄
                progress?.Report(new ServerBackupProgressReport(80, "正在還原備份檔案至伺服器目錄...", 0, 0));

                SafeFileSystem.MoveChildren(
                    stagingDir,
                    serverDir,
                    beforeMove: (entry, _) => SafeFileSystem.ClearReadOnlyAttribute(entry.FullPath));

                // 階段四：將現場保留之診斷記錄檔安全合併移回伺服器目錄
                if (hasPreservedLogs)
                {
                    progress?.Report(new ServerBackupProgressReport(92, "正在合併保留之診斷記錄檔...", 0, 0));
                    RestorePreservedDiagnostics(preservedLogsDir, serverDir);
                }

                // 還原成功後清理 rollback 快照與 staging 暫存目錄
                progress?.Report(new ServerBackupProgressReport(96, "正在清理暫存快照環境...", 0, 0));
                SafeFileSystem.DeleteWithin(_resolvedServersRoot, rollbackDir);
                SafeFileSystem.DeleteWithin(_resolvedServersRoot, stagingDir);
                SafeFileSystem.DeleteWithin(_resolvedServersRoot, preservedLogsDir);

                progress?.Report(new ServerBackupProgressReport(100, "備份還原完成！", 0, 0));
                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "還原備份失敗，執行交易復原");
                // 發生例外時自動執行交易復原
                bool rollbackSucceeded = false;
                try
                {
                    if (SafeFileSystem.DirectoryExists(rollbackDir))
                    {
                        if (snapshotCompleted)
                        {
                            // 快照完成後先清除已搬入的還原內容，避免新舊檔案混雜；單項失敗不阻擋搬回快照
                            RemoveRestoredLeftovers(serverDir);
                        }

                        SafeFileSystem.MoveChildren(
                            rollbackDir,
                            serverDir,
                            beforeMove: (_, targetLive) =>
                            {
                                SafeFileSystem.RetryOnTransientIo(
                                    () =>
                                    {
                                        if (SafeFileSystem.FileExists(targetLive))
                                        {
                                            SafeFileSystem.ClearReadOnlyAttribute(targetLive);
                                            SafeFileSystem.DeleteFile(targetLive);
                                        }
                                        else if (SafeFileSystem.DirectoryExists(targetLive))
                                        {
                                            SafeFileSystem.ClearReadOnlyAttribute(targetLive);
                                            SafeFileSystem.DeleteDirectory(targetLive, recursive: true);
                                        }
                                    },
                                    targetLive,
                                    maxAttempts: 3,
                                    baseDelay: TimeSpan.FromMilliseconds(100),
                                    shouldRetry: static (ioEx, _) => ioEx is IOException or UnauthorizedAccessException);
                            });
                    }

                    rollbackSucceeded = true;
                }
                catch (Exception rbEx) when (rbEx is not OperationCanceledException)
                {
                    Logger.Error(rbEx, "還原失敗後嘗試復原現場檔案時發生錯誤，保留快照目錄供人工復原: {RollbackDir}", rollbackDir);
                }
                finally
                {
                    // 復原未完成時快照內仍有原始檔案，不可刪除
                    if (rollbackSucceeded)
                    {
                        SafeFileSystem.DeleteWithin(_resolvedServersRoot, rollbackDir);
                    }

                    SafeFileSystem.DeleteWithin(_resolvedServersRoot, stagingDir);
                    SafeFileSystem.DeleteWithin(_resolvedServersRoot, preservedLogsDir);
                }

                if (ex is OperationCanceledException)
                {
                    throw;
                }

                return false;
            }
        }, cancellationToken).ConfigureAwait(false);
    }

    public Task<bool> DeleteBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(backupFileName);
        cancellationToken.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(backupDirectory))
        {
            return Task.FromResult(false);
        }

        // 只允許刪除屬於該伺服器的備份檔，名稱不得含路徑
        if (!string.Equals(Path.GetFileName(backupFileName), backupFileName, StringComparison.Ordinal)
            || !IsBackupFileFor(serverName, backupFileName))
        {
            Logger.Warning("拒絕刪除非該伺服器之備份檔: {Server}: {FileName}", serverName, backupFileName);
            return Task.FromResult(false);
        }

        return Task.Run(() =>
        {
            string backupsDir = ResolveExternalBackupDirectory(backupDirectory);
            string targetPath = Path.Combine(backupsDir, backupFileName);
            if (!SafeFileSystem.IsPathWithin(backupsDir, targetPath, strict: true) || !SafeFileSystem.FileExists(targetPath))
            {
                return false;
            }

            SafeFileSystem.DeleteFile(targetPath);
            return true;
        }, cancellationToken);
    }

    private async Task PruneOldBackupsAsync(
        string serverName,
        string backupDirectory,
        CancellationToken cancellationToken)
    {
        var existing = await ListBackupsAsync(serverName, backupDirectory, cancellationToken).ConfigureAwait(false);
        int maxRetentionCount = Math.Max(ServerDefaults.MinBackupRetentionCount, _retentionCountProvider());
        if (existing.Count <= maxRetentionCount)
        {
            return;
        }

        foreach (var backup in existing.Skip(maxRetentionCount))
        {
            try
            {
                await DeleteBackupAsync(serverName, backup.FileName, backupDirectory, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // 單筆清理失敗不影響已完成的備份
                Logger.Warning(ex, "清理舊備份失敗: {FileName}", backup.FileName);
            }
        }
    }

    /// <summary>伺服器名稱須為單一路徑段且解析後位於伺服器根目錄內</summary>
    private string GetServerDirectory(string serverName) =>
        ServerSetupHelpers.ResolveServerDirectory(_resolvedServersRoot, serverName);

    /// <summary>逐項刪除伺服器目錄內已搬入的還原內容（保留 backups），失敗項目重試後記錄警告</summary>
    private static void RemoveRestoredLeftovers(string serverDir)
    {
        string keptBackupsDir = Path.Combine(serverDir, ServerDefaults.BackupsDirectoryName);
        foreach (var leftover in SafeFileSystem.ListBoundedDirectory(serverDir, rejectReparse: false))
        {
            if (string.Equals(leftover.FullPath, keptBackupsDir, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            try
            {
                SafeFileSystem.RetryOnTransientIo(
                    () =>
                    {
                        if (leftover.IsDirectory)
                        {
                            SafeFileSystem.DeleteDirectory(leftover.FullPath, recursive: true);
                        }
                        else
                        {
                            SafeFileSystem.DeleteFile(leftover.FullPath);
                        }
                    },
                    leftover.FullPath,
                    CleanupRetryCount,
                    CleanupRetryDelay,
                    static (ex, _) => ex is IOException or UnauthorizedAccessException);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning(ex, "交易復原時無法清除還原殘留: {Path}", leftover.FullPath);
            }
        }
    }

    private string ResolveExternalBackupDirectory(string backupDirectory)
    {
        string resolved = SafeFileSystem.ResolveStableDirectory(backupDirectory, create: true);
        if (IsInsideServersRoot(resolved))
        {
            throw new InvalidOperationException("備份資料夾不得位於伺服器根目錄 (servers/) 或其子目錄內");
        }

        return resolved;
    }

    /// <summary>路徑是否位於伺服器存放目錄或其子目錄內（備份不得存放於此）</summary>
    private bool IsInsideServersRoot(string path) =>
        SafeFileSystem.IsPathWithin(Path.GetFullPath(_resolvedServersRoot), Path.GetFullPath(path), strict: false);

    private static void PreserveLiveDiagnostics(string serverDir, string destinationDir, CancellationToken cancellationToken = default)
    {
        string liveLogs = Path.Combine(serverDir, ServerDefaults.LogsDirectoryName);
        string liveCrash = Path.Combine(serverDir, ServerDefaults.CrashReportsDirectoryName);

        if (SafeFileSystem.DirectoryExists(liveLogs))
        {
            SafeFileSystem.CopyDirectoryTreeSafe(liveLogs, Path.Combine(destinationDir, ServerDefaults.LogsDirectoryName), cancellationToken);
        }
        if (SafeFileSystem.DirectoryExists(liveCrash))
        {
            SafeFileSystem.CopyDirectoryTreeSafe(liveCrash, Path.Combine(destinationDir, ServerDefaults.CrashReportsDirectoryName), cancellationToken);
        }
    }

    private static void RestorePreservedDiagnostics(string sourceDir, string serverDir)
    {
        MergeMissingFiles(Path.Combine(sourceDir, ServerDefaults.CrashReportsDirectoryName), Path.Combine(serverDir, ServerDefaults.CrashReportsDirectoryName));
        MergeMissingFiles(Path.Combine(sourceDir, ServerDefaults.LogsDirectoryName), Path.Combine(serverDir, ServerDefaults.LogsDirectoryName), static (file, targetFile) =>
        {
            // 還原出的 latest.log 已存在時，現場記錄另存為 pre-restore；該名稱已被占用則加時間戳記
            if (!string.Equals(Path.GetFileName(file), ServerDefaults.LatestLogFileName, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            string targetDir = Path.GetDirectoryName(targetFile)!;
            string preRestoreFile = Path.Combine(targetDir, "latest.log.pre-restore");
            if (SafeFileSystem.FileExists(preRestoreFile))
            {
                string stamp = DateTime.Now.ToString(TimestampFormat, CultureInfo.InvariantCulture);
                preRestoreFile = Path.Combine(targetDir, $"latest.log.pre-restore-{stamp}");
            }

            if (!SafeFileSystem.FileExists(preRestoreFile))
            {
                SafeFileSystem.CopyFile(file, preRestoreFile);
            }
        });
    }

    /// <summary>遞迴把來源資料夾中目標沒有的檔案複製過去；同名檔交由 onExisting（來源檔、目標檔）處理</summary>
    private static void MergeMissingFiles(string sourceDir, string targetDir, Action<string, string>? onExisting = null)
    {
        if (!SafeFileSystem.DirectoryExists(sourceDir))
        {
            return;
        }

        SafeFileSystem.CreateDirectory(targetDir);
        foreach (var entry in SafeFileSystem.EnumerateBoundedTree(sourceDir))
        {
            string targetPath = Path.Combine(targetDir, Path.GetRelativePath(sourceDir, entry.FullPath));
            if (entry.IsDirectory)
            {
                SafeFileSystem.CreateDirectory(targetPath);
            }
            else if (!SafeFileSystem.FileExists(targetPath))
            {
                SafeFileSystem.CreateDirectory(Path.GetDirectoryName(targetPath)!);
                SafeFileSystem.CopyFile(entry.FullPath, targetPath);
            }
            else
            {
                onExisting?.Invoke(entry.FullPath, targetPath);
            }
        }
    }
}
