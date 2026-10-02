using System.Globalization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器備份與交易式還原服務
/// </summary>
public sealed class ServerBackupService(string serversRoot, int maxRetentionCount = 10) : IServerBackupService
{
    private readonly string _resolvedServersRoot = SafeFileSystem.ResolveStableDirectory(serversRoot);
    private readonly int _maxRetentionCount = Math.Max(1, maxRetentionCount);

    public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(
        string serverName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        cancellationToken.ThrowIfCancellationRequested();

        string backupsDir = ResolveBackupDirectory(serverName, backupDirectory);
        if (!Directory.Exists(backupsDir))
        {
            return Task.FromResult<IReadOnlyList<ServerBackupInfo>>([]);
        }

        var list = new List<ServerBackupInfo>();
        var entries = SafeFileSystem.ListBoundedDirectory(backupsDir, rejectReparse: false);
        foreach (var entry in entries)
        {
            if (!entry.IsDirectory && entry.FullPath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
            {
                var fileInfo = new FileInfo(entry.FullPath);
                list.Add(new ServerBackupInfo(
                    FileName: Path.GetFileName(entry.FullPath),
                    FullPath: entry.FullPath,
                    SizeBytes: fileInfo.Length,
                    CreatedAt: fileInfo.CreationTimeUtc));
            }
        }

        return Task.FromResult<IReadOnlyList<ServerBackupInfo>>([.. list.OrderByDescending(b => b.CreatedAt)]);
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
        if (!Directory.Exists(serverDir))
        {
            throw new DirectoryNotFoundException($"找不到伺服器目錄：{serverDir}");
        }

        // 驗證備份路徑不在 servers 根目錄內（安全邊界防護）
        string backupsDir = GetBackupsDirectory(serverName);
        if (!string.IsNullOrWhiteSpace(destinationPath))
        {
            string normalizedDest = Path.GetFullPath(destinationPath);
            string normalizedServersRoot = Path.GetFullPath(_resolvedServersRoot);
            if (SafeFileSystem.IsPathWithin(normalizedServersRoot, normalizedDest, strict: false))
            {
                throw new InvalidOperationException("備份路徑不得位於伺服器根目錄 (servers/) 內，請選擇其他儲存位置");
            }
        }

        string timestamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        string shortId = Guid.NewGuid().ToString("N")[..6];
        string backupFileName = $"backup-{serverName}-{timestamp}-{shortId}.zip";

        string backupDirectory;
        string backupFilePath;
        if (!string.IsNullOrWhiteSpace(destinationPath))
        {
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
        }
        else
        {
            backupDirectory = SafeFileSystem.ResolveStableDirectory(backupsDir, create: true);
            backupFilePath = Path.Combine(backupDirectory, backupFileName);
        }

        var entries = SafeFileSystem.WalkBoundedTree(serverDir, rejectReparse: true);
        var filesToBackup = entries
            .Where(e => !e.IsDirectory)
            .Where(e =>
            {
                string filePath = e.FullPath;
                ReadOnlySpan<char> rel = Path.GetRelativePath(serverDir, filePath).AsSpan();
                int sepIdx = rel.IndexOfAny(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                ReadOnlySpan<char> firstSegment = sepIdx >= 0 ? rel[..sepIdx] : rel;

                if (firstSegment.Equals("logs", StringComparison.OrdinalIgnoreCase) ||
                    firstSegment.Equals("crash-reports", StringComparison.OrdinalIgnoreCase))
                {
                    return false;
                }

                return !SafeFileSystem.IsPathWithin(backupsDir, filePath, strict: false) &&
                       !filePath.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase) &&
                       !filePath.EndsWith(".lock", StringComparison.OrdinalIgnoreCase);
            })
            .ToList();

        long totalBytes = filesToBackup.Sum(f => f.Length);
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

        var fileInfo = new FileInfo(backupFilePath);

        // 依備份保留政策自動清理最舊備份
        await PruneOldBackupsAsync(serverName, backupDirectory, cancellationToken).ConfigureAwait(false);

        return new ServerBackupInfo(
            FileName: fileInfo.Name,
            FullPath: fileInfo.FullName,
            SizeBytes: fileInfo.Length,
            CreatedAt: fileInfo.CreationTimeUtc);
    }

    public async Task<bool> RestoreBackupAsync(
        string serverName,
        string backupFileName,
        string? backupDirectory = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(backupFileName);
        cancellationToken.ThrowIfCancellationRequested();

        string serverDir = GetServerDirectory(serverName);
        string backupsDir = ResolveBackupDirectory(serverName, backupDirectory);
        string backupFilePath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (!File.Exists(backupFilePath))
        {
            return false;
        }

        string stagingDir = Path.Combine(_resolvedServersRoot, $".restore-staging-{Guid.NewGuid():N}");
        string rollbackDir = Path.Combine(_resolvedServersRoot, $".restore-rollback-{Guid.NewGuid():N}");
        string preservedLogsDir = Path.Combine(_resolvedServersRoot, $".restore-preserved-logs-{Guid.NewGuid():N}");
        bool hasPreservedLogs = false;

        try
        {
            // 階段零：暫存現場之 logs 與 crash-reports，防止災難復原時遺失關鍵診斷日誌
            if (Directory.Exists(serverDir))
            {
                PreserveLiveDiagnostics(serverDir, preservedLogsDir);
                hasPreservedLogs = Directory.Exists(preservedLogsDir) && Directory.EnumerateFileSystemEntries(preservedLogsDir).Any();
            }

            // 階段一：在暫存 staging 目錄進行解壓與完整性校驗
            Directory.CreateDirectory(stagingDir);
            SafeZipArchive.Extract(backupFilePath, stagingDir);

            // 階段二：建立既有伺服器檔案之 rollback 快照
            Directory.CreateDirectory(rollbackDir);
            var currentEntries = SafeFileSystem.ListBoundedDirectory(serverDir, rejectReparse: false);
            foreach (var entry in currentEntries)
            {
                // 保留 backups 目錄不移動
                if (string.Equals(entry.FullPath, backupsDir, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                string relName = Path.GetFileName(entry.FullPath);
                string targetRollback = Path.Combine(rollbackDir, relName);

                if (entry.IsDirectory)
                {
                    Directory.Move(entry.FullPath, targetRollback);
                }
                else
                {
                    File.Move(entry.FullPath, targetRollback);
                }
            }

            // 階段三：將 staging 中的還原內容搬移至伺服器目錄
            var stagingEntries = SafeFileSystem.ListBoundedDirectory(stagingDir, rejectReparse: false);
            foreach (var sEntry in stagingEntries)
            {
                string relName = Path.GetFileName(sEntry.FullPath);
                string targetLive = Path.Combine(serverDir, relName);

                if (sEntry.IsDirectory)
                {
                    Directory.Move(sEntry.FullPath, targetLive);
                }
                else
                {
                    File.Move(sEntry.FullPath, targetLive);
                }
            }

            // 階段四：將現場保留之診斷日誌安全合併移回伺服器目錄
            if (hasPreservedLogs)
            {
                RestorePreservedDiagnostics(preservedLogsDir, serverDir);
            }

            // 還原成功後清理 rollback 快照與 staging 暫存目錄
            CleanDirectorySafe(rollbackDir);
            CleanDirectorySafe(stagingDir);
            CleanDirectorySafe(preservedLogsDir);
            return true;
        }
        catch
        {
            // 發生異常時自動執行交易復原
            try
            {
                if (Directory.Exists(rollbackDir))
                {
                    var rollbackEntries = SafeFileSystem.ListBoundedDirectory(rollbackDir, rejectReparse: false);
                    foreach (var rbEntry in rollbackEntries)
                    {
                        string relName = Path.GetFileName(rbEntry.FullPath);
                        string targetLive = Path.Combine(serverDir, relName);

                        if (File.Exists(targetLive))
                        {
                            File.Delete(targetLive);
                        }
                        else if (Directory.Exists(targetLive))
                        {
                            Directory.Delete(targetLive, recursive: true);
                        }

                        if (rbEntry.IsDirectory)
                        {
                            Directory.Move(rbEntry.FullPath, targetLive);
                        }
                        else
                        {
                            File.Move(rbEntry.FullPath, targetLive);
                        }
                    }
                }
            }
            catch
            {
            }
            finally
            {
                CleanDirectorySafe(rollbackDir);
                CleanDirectorySafe(stagingDir);
            }

            return false;
        }
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

        string backupsDir = ResolveBackupDirectory(serverName, backupDirectory);
        string targetPath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (File.Exists(targetPath))
        {
            File.Delete(targetPath);
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

    private string GetBackupsDirectory(string serverName) =>
        Path.Combine(GetServerDirectory(serverName), "backups");

    private string ResolveBackupDirectory(string serverName, string? backupDirectory)
    {
        string defaultBackupsDir = GetBackupsDirectory(serverName);
        if (string.IsNullOrWhiteSpace(backupDirectory) ||
            string.Equals(Path.GetFullPath(backupDirectory), Path.GetFullPath(defaultBackupsDir), StringComparison.OrdinalIgnoreCase))
        {
            return defaultBackupsDir;
        }

        return ResolveExternalBackupDirectory(backupDirectory);
    }

    private string ResolveExternalBackupDirectory(string backupDirectory)
    {
        string resolved = SafeFileSystem.ResolveStableDirectory(backupDirectory, create: true);
        string normalizedRoot = Path.GetFullPath(_resolvedServersRoot);
        string normalizedBackup = Path.GetFullPath(resolved);
        if (SafeFileSystem.IsPathWithin(normalizedRoot, normalizedBackup, strict: false))
        {
            throw new InvalidOperationException("外部備份資料夾不得位於伺服器根目錄 (servers/) 內");
        }

        return resolved;
    }

    private static void CleanDirectorySafe(string dirPath)
    {
        try
        {
            if (Directory.Exists(dirPath))
            {
                Directory.Delete(dirPath, recursive: true);
            }
        }
        catch
        {
        }
    }

    private static void PreserveLiveDiagnostics(string serverDir, string destinationDir)
    {
        string liveLogs = Path.Combine(serverDir, "logs");
        string liveCrash = Path.Combine(serverDir, "crash-reports");

        if (Directory.Exists(liveLogs))
        {
            CopyDirectoryContent(liveLogs, Path.Combine(destinationDir, "logs"));
        }
        if (Directory.Exists(liveCrash))
        {
            CopyDirectoryContent(liveCrash, Path.Combine(destinationDir, "crash-reports"));
        }
    }

    private static void RestorePreservedDiagnostics(string sourceDir, string serverDir)
    {
        string preservedCrash = Path.Combine(sourceDir, "crash-reports");
        string preservedLogs = Path.Combine(sourceDir, "logs");

        if (Directory.Exists(preservedCrash))
        {
            string targetCrash = Path.Combine(serverDir, "crash-reports");
            Directory.CreateDirectory(targetCrash);
            foreach (string file in Directory.EnumerateFiles(preservedCrash))
            {
                string targetFile = Path.Combine(targetCrash, Path.GetFileName(file));
                if (!File.Exists(targetFile))
                {
                    File.Copy(file, targetFile);
                }
            }
        }

        if (Directory.Exists(preservedLogs))
        {
            string targetLogs = Path.Combine(serverDir, "logs");
            Directory.CreateDirectory(targetLogs);
            foreach (string file in Directory.EnumerateFiles(preservedLogs))
            {
                string fileName = Path.GetFileName(file);
                string targetFile = Path.Combine(targetLogs, fileName);
                if (!File.Exists(targetFile))
                {
                    File.Copy(file, targetFile);
                }
                else if (string.Equals(fileName, "latest.log", StringComparison.OrdinalIgnoreCase))
                {
                    string preRestoreFile = Path.Combine(targetLogs, "latest.log.pre-restore");
                    if (!File.Exists(preRestoreFile))
                    {
                        File.Copy(file, preRestoreFile);
                    }
                }
            }
        }
    }

    private static void CopyDirectoryContent(string sourceDir, string targetDir)
    {
        Directory.CreateDirectory(targetDir);
        foreach (string file in Directory.EnumerateFiles(sourceDir))
        {
            File.Copy(file, Path.Combine(targetDir, Path.GetFileName(file)), overwrite: true);
        }
        foreach (string subDir in Directory.EnumerateDirectories(sourceDir))
        {
            CopyDirectoryContent(subDir, Path.Combine(targetDir, Path.GetFileName(subDir)));
        }
    }
}
