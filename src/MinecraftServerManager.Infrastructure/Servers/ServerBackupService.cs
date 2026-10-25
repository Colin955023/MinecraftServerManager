using MinecraftServerManager.Infrastructure.Logging;
using System.Globalization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器備份與交易式還原服務
/// </summary>
public sealed class ServerBackupService(string serversRoot, int maxRetentionCount = 10) : IServerBackupService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerBackupService");
    private readonly string _resolvedServersRoot = SafeFileSystem.ResolveStableDirectory(serversRoot);
    private readonly int _maxRetentionCount = Math.Max(1, maxRetentionCount);

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

        string backupsDir = ResolveExternalBackupDirectory(backupDirectory);
        if (!SafeFileSystem.DirectoryExists(backupsDir))
        {
            return Task.FromResult<IReadOnlyList<ServerBackupInfo>>([]);
        }

        var list = new List<ServerBackupInfo>();
        var entries = SafeFileSystem.ListBoundedDirectory(backupsDir, rejectReparse: false);
        string prefix = $"backup-{serverName}-";
        foreach (var entry in entries)
        {
            if (!entry.IsDirectory && entry.FullPath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
            {
                string fn = Path.GetFileName(entry.FullPath);
                if (fn.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
                    fn.StartsWith($"{serverName}-", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(fn, $"backup-{serverName}.zip", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(fn, $"{serverName}.zip", StringComparison.OrdinalIgnoreCase))
                {
                    FileSystemMetadata fileInfo = SafeFileSystem.GetFileMetadata(entry.FullPath);
                    list.Add(new ServerBackupInfo(
                        FileName: fn,
                        FullPath: entry.FullPath,
                        SizeBytes: fileInfo.Length,
                        CreatedAt: fileInfo.CreationTimeUtc));
                }
            }
        }

        return Task.FromResult<IReadOnlyList<ServerBackupInfo>>([.. list.OrderByDescending(static b => b.CreatedAt)]);
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

        string normalizedDest = Path.GetFullPath(destinationPath);
        string normalizedServersRoot = Path.GetFullPath(_resolvedServersRoot);
        if (SafeFileSystem.IsPathWithin(normalizedServersRoot, normalizedDest, strict: false))
        {
            throw new InvalidOperationException("備份路徑不得位於伺服器根目錄 (servers/) 或其子目錄內，請選擇其他儲存位置");
        }

        string timestamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        string shortId = Guid.NewGuid().ToString("N")[..6];
        string backupFileName = $"backup-{serverName}-{timestamp}-{shortId}.zip";

        string backupDirectory;
        string backupFilePath;
        if (destinationPath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
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

        string legacyBackupsDir = Path.Combine(serverDir, "backups");
        string legacyBackupsPrefix = Path.TrimEndingDirectorySeparator(Path.GetFullPath(legacyBackupsDir)) + Path.DirectorySeparatorChar;

        await Task.Run(() =>
        {
            List<FileSystemEntry> filesToBackup;
            try
            {
                var entries = SafeFileSystem.EnumerateBoundedTree(
                    serverDir,
                    rejectReparse: true,
                    pruneDirectory: static (fullPath, name) =>
                        name.Equals("logs", StringComparison.OrdinalIgnoreCase) ||
                        name.Equals("crash-reports", StringComparison.OrdinalIgnoreCase) ||
                        name.Equals("backups", StringComparison.OrdinalIgnoreCase));

                filesToBackup = entries
                    .Where(static e => !e.IsDirectory)
                    .Where(e =>
                    {
                        string filePath = e.FullPath;
                        ReadOnlySpan<char> rel = Path.GetRelativePath(serverDir, filePath);
                        int sepIdx = rel.IndexOfAny(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                        ReadOnlySpan<char> firstSegment = sepIdx >= 0 ? rel[..sepIdx] : rel;

                        if (firstSegment.Equals("logs", StringComparison.OrdinalIgnoreCase) ||
                            firstSegment.Equals("crash-reports", StringComparison.OrdinalIgnoreCase))
                        {
                            return false;
                        }

                        bool isUnderBackups = filePath.StartsWith(legacyBackupsPrefix, StringComparison.OrdinalIgnoreCase) ||
                                              filePath.Equals(legacyBackupsDir, StringComparison.OrdinalIgnoreCase);

                        return !isUnderBackups &&
                               !filePath.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase) &&
                               !filePath.EndsWith(".lock", StringComparison.OrdinalIgnoreCase);
                    })
                    .ToList();
            }
            catch (SafeFileSystemException ex) when (ex.Message.Contains("安全上限", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException($"伺服器檔案數量或大小超過安全備份上限（安全上限：{SafeFileSystem.DefaultMaxEntries} 個項目或 128 GB）。請清理地圖快取或暫存檔案後重試。", ex);
            }

            long totalBytes = filesToBackup.Sum(static f => f.Length);
            long processedBytes = 0;

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

                    progress?.Report(new ServerBackupProgressReport(
                        PercentCompleted: totalBytes > 0 ? (int)(processedBytes * 100 / totalBytes) : 0,
                        CurrentFile: relativePath,
                        ProcessedBytes: processedBytes,
                        TotalBytes: totalBytes));
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
            CreatedAt: fileInfo.CreationTimeUtc);
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

        string serverDir = GetServerDirectory(serverName);
        string backupsDir = ResolveExternalBackupDirectory(backupDirectory);
        string backupFilePath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (!SafeFileSystem.FileExists(backupFilePath))
        {
            return false;
        }

        string stagingDir = Path.Combine(_resolvedServersRoot, $".restore-staging-{Guid.NewGuid():N}");
        string rollbackDir = Path.Combine(_resolvedServersRoot, $".restore-rollback-{Guid.NewGuid():N}");
        string preservedLogsDir = Path.Combine(_resolvedServersRoot, $".restore-preserved-logs-{Guid.NewGuid():N}");
        bool hasPreservedLogs = false;

        progress?.Report(new ServerBackupProgressReport(5, "正在暫存現場診斷記錄檔...", 0, 0));

        return await Task.Run(() =>
        {
            try
            {
                // 階段零：暫存現場之 logs 與 crash-reports，防止災難復原時遺失關鍵診斷記錄檔
                if (SafeFileSystem.DirectoryExists(serverDir))
                {
                    SafeFileSystem.RemoveReadOnlyAttributesRecursive(serverDir);
                    PreserveLiveDiagnostics(serverDir, preservedLogsDir);
                    hasPreservedLogs = SafeFileSystem.DirectoryExists(preservedLogsDir) && SafeFileSystem.EnumerateFileSystemEntries(preservedLogsDir).Any();
                }

                // 階段一：在暫存 staging 目錄解壓並校驗完整性
                SafeFileSystem.CreateDirectory(stagingDir);
                progress?.Report(new ServerBackupProgressReport(10, "正在解壓縮備份檔案...", 0, 0));
                SafeZipArchive.Extract(backupFilePath, stagingDir, (extracted, total) =>
                {
                    int pct = total > 0 ? (int)(10 + (extracted * 50 / total)) : 35;
                    progress?.Report(new ServerBackupProgressReport(Math.Clamp(pct, 10, 60), $"正在解壓縮檔案 ({Math.Clamp(pct, 10, 60)}%)...", extracted, total));
                });
                SafeFileSystem.RemoveReadOnlyAttributesRecursive(stagingDir);

                // 階段二：建立既有伺服器檔案之 rollback 快照
                progress?.Report(new ServerBackupProgressReport(65, "正在建立伺服器現況快照...", 0, 0));
                SafeFileSystem.CreateDirectory(rollbackDir);
                var currentEntries = SafeFileSystem.ListBoundedDirectory(serverDir, rejectReparse: false);
                string legacyBackupsDir = Path.Combine(serverDir, "backups");
                foreach (var entry in currentEntries)
                {
                    // 保留歷史 backups 目錄不移動
                    if (string.Equals(entry.FullPath, legacyBackupsDir, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    string relName = Path.GetFileName(entry.FullPath);
                    string targetRollback = Path.Combine(rollbackDir, relName);

                    SafeFileSystem.ClearReadOnlyAttribute(entry.FullPath);
                    SafeFileSystem.MovePath(entry.FullPath, targetRollback);
                }

                // 階段三：將 staging 中的還原內容搬移至伺服器目錄
                progress?.Report(new ServerBackupProgressReport(80, "正在還原備份檔案至伺服器目錄...", 0, 0));
                var stagingEntries = SafeFileSystem.ListBoundedDirectory(stagingDir, rejectReparse: false);
                foreach (var sEntry in stagingEntries)
                {
                    string relName = Path.GetFileName(sEntry.FullPath);
                    string targetLive = Path.Combine(serverDir, relName);

                    SafeFileSystem.ClearReadOnlyAttribute(sEntry.FullPath);
                    SafeFileSystem.MovePath(sEntry.FullPath, targetLive);
                }

                // 階段四：將現場保留之診斷記錄檔安全合併移回伺服器目錄
                if (hasPreservedLogs)
                {
                    progress?.Report(new ServerBackupProgressReport(92, "正在合併保留之診斷記錄檔...", 0, 0));
                    RestorePreservedDiagnostics(preservedLogsDir, serverDir);
                }

                // 還原成功後清理 rollback 快照與 staging 暫存目錄
                progress?.Report(new ServerBackupProgressReport(96, "正在清理暫存快照環境...", 0, 0));
                CleanDirectorySafe(rollbackDir);
                CleanDirectorySafe(stagingDir);
                CleanDirectorySafe(preservedLogsDir);

                progress?.Report(new ServerBackupProgressReport(100, "備份還原完成！", 0, 0));
                return true;
            }
            catch
            {
                // 發生異常時自動執行交易復原
                try
                {
                    if (SafeFileSystem.DirectoryExists(rollbackDir))
                    {
                        var rollbackEntries = SafeFileSystem.ListBoundedDirectory(rollbackDir, rejectReparse: false);
                        foreach (var rbEntry in rollbackEntries)
                        {
                            string relName = Path.GetFileName(rbEntry.FullPath);
                            string targetLive = Path.Combine(serverDir, relName);

                            if (SafeFileSystem.FileExists(targetLive))
                            {
                                SafeFileSystem.DeleteFile(targetLive);
                            }
                            else if (SafeFileSystem.DirectoryExists(targetLive))
                            {
                                SafeFileSystem.DeleteDirectory(targetLive, recursive: true);
                            }

                            SafeFileSystem.MovePath(rbEntry.FullPath, targetLive);
                        }
                    }
                }
                catch (Exception rbEx) when (rbEx is not OperationCanceledException)
                {
                    Logger.Error(rbEx, "還原失敗後嘗試復原現場檔案時發生錯誤");
                }
                finally
                {
                    CleanDirectorySafe(rollbackDir);
                    CleanDirectorySafe(stagingDir);
                    CleanDirectorySafe(preservedLogsDir);
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

        string backupsDir = ResolveExternalBackupDirectory(backupDirectory);
        string targetPath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (SafeFileSystem.FileExists(targetPath))
        {
            SafeFileSystem.DeleteFile(targetPath);
            return Task.FromResult(true);
        }

        return Task.FromResult(false);
    }

    private async Task PruneOldBackupsAsync(
        string serverName,
        string backupDirectory,
        CancellationToken cancellationToken)
    {
        var existing = await ListBackupsAsync(serverName, backupDirectory, cancellationToken).ConfigureAwait(false);
        if (existing.Count <= _maxRetentionCount)
        {
            return;
        }

        var toRemove = existing.Skip(_maxRetentionCount).ToList();
        foreach (var backup in toRemove)
        {
            await DeleteBackupAsync(serverName, backup.FileName, backupDirectory, cancellationToken).ConfigureAwait(false);
        }
    }

    private string GetServerDirectory(string serverName) =>
        SafeFileSystem.ResolveStableDirectory(Path.Combine(_resolvedServersRoot, serverName));

    private string ResolveExternalBackupDirectory(string backupDirectory)
    {
        string resolved = SafeFileSystem.ResolveStableDirectory(backupDirectory, create: true);
        string normalizedRoot = Path.GetFullPath(_resolvedServersRoot);
        string normalizedBackup = Path.GetFullPath(resolved);
        if (SafeFileSystem.IsPathWithin(normalizedRoot, normalizedBackup, strict: false))
        {
            throw new InvalidOperationException("備份資料夾不得位於伺服器根目錄 (servers/) 或其子目錄內");
        }

        return resolved;
    }

    private static void CleanDirectorySafe(string dirPath)
    {
        try
        {
            if (SafeFileSystem.DirectoryExists(dirPath))
            {
                SafeFileSystem.DeleteDirectory(dirPath, recursive: true);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("安全清理目錄失敗: {0}", ex.Message);
        }
    }

    private static void PreserveLiveDiagnostics(string serverDir, string destinationDir)
    {
        string liveLogs = Path.Combine(serverDir, "logs");
        string liveCrash = Path.Combine(serverDir, "crash-reports");

        if (SafeFileSystem.DirectoryExists(liveLogs))
        {
            SafeFileSystem.CopyDirectoryTreeSafe(liveLogs, Path.Combine(destinationDir, "logs"));
        }
        if (SafeFileSystem.DirectoryExists(liveCrash))
        {
            SafeFileSystem.CopyDirectoryTreeSafe(liveCrash, Path.Combine(destinationDir, "crash-reports"));
        }
    }

    private static void RestorePreservedDiagnostics(string sourceDir, string serverDir)
    {
        string preservedCrash = Path.Combine(sourceDir, "crash-reports");
        string preservedLogs = Path.Combine(sourceDir, "logs");

        if (SafeFileSystem.DirectoryExists(preservedCrash))
        {
            string targetCrash = Path.Combine(serverDir, "crash-reports");
            SafeFileSystem.CreateDirectory(targetCrash);
            foreach (string file in SafeFileSystem.EnumerateFiles(preservedCrash, "*"))
            {
                string targetFile = Path.Combine(targetCrash, Path.GetFileName(file));
                if (!SafeFileSystem.FileExists(targetFile))
                {
                    SafeFileSystem.CopyFile(file, targetFile);
                }
            }
        }

        if (SafeFileSystem.DirectoryExists(preservedLogs))
        {
            string targetLogs = Path.Combine(serverDir, "logs");
            SafeFileSystem.CreateDirectory(targetLogs);
            foreach (string file in SafeFileSystem.EnumerateFiles(preservedLogs, "*"))
            {
                string fileName = Path.GetFileName(file);
                string targetFile = Path.Combine(targetLogs, fileName);
                if (!SafeFileSystem.FileExists(targetFile))
                {
                    SafeFileSystem.CopyFile(file, targetFile);
                }
                else if (string.Equals(fileName, "latest.log", StringComparison.OrdinalIgnoreCase))
                {
                    string preRestoreFile = Path.Combine(targetLogs, "latest.log.pre-restore");
                    if (!SafeFileSystem.FileExists(preRestoreFile))
                    {
                        SafeFileSystem.CopyFile(file, preRestoreFile);
                    }
                }
            }
        }
    }
}
