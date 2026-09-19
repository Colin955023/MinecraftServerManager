using System.Globalization;
using System.IO.Compression;
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

    public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(string serverName, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        cancellationToken.ThrowIfCancellationRequested();

        string backupsDir = GetBackupsDirectory(serverName);
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

        return Task.FromResult<IReadOnlyList<ServerBackupInfo>>(list.OrderByDescending(b => b.CreatedAt).ToList());
    }

    public async Task<ServerBackupInfo> CreateBackupAsync(
        string serverName,
        string? comment = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        cancellationToken.ThrowIfCancellationRequested();

        string serverDir = GetServerDirectory(serverName);
        if (!Directory.Exists(serverDir))
        {
            throw new DirectoryNotFoundException($"找不到伺服器目錄：{serverDir}");
        }

        string backupsDir = GetBackupsDirectory(serverName);
        SafeFileSystem.ResolveStableDirectory(backupsDir, create: true);

        string timestamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        string shortId = Guid.NewGuid().ToString("N")[..6];
        string backupFileName = $"backup-{serverName}-{timestamp}-{shortId}.zip";
        string backupFilePath = Path.Combine(backupsDir, backupFileName);
        string tempZipPath = backupFilePath + "." + Guid.NewGuid().ToString("N") + ".tmp";

        try
        {
            using (var zipStream = new FileStream(tempZipPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            using (var archive = new ZipArchive(zipStream, ZipArchiveMode.Create, leaveOpen: false))
            {
                if (!string.IsNullOrWhiteSpace(comment))
                {
                    archive.Comment = comment;
                }

                // 透過受限走訪樹確保邊界安全防護與防止符號連結逃逸
                var entries = SafeFileSystem.WalkBoundedTree(serverDir, rejectReparse: true);
                foreach (var entry in entries)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    if (entry.IsDirectory)
                    {
                        continue;
                    }

                    string filePath = entry.FullPath;

                    // 排除 backups 目錄自身與暫存/鎖定檔案
                    if (SafeFileSystem.IsPathWithin(backupsDir, filePath, strict: false) ||
                        filePath.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase) ||
                        filePath.EndsWith(".lock", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    string relativePath = Path.GetRelativePath(serverDir, filePath);
                    await archive.CreateEntryFromFileAsync(filePath, relativePath, CompressionLevel.Optimal, cancellationToken).ConfigureAwait(false);
                }
            }

            File.Move(tempZipPath, backupFilePath, overwrite: true);
            var fileInfo = new FileInfo(backupFilePath);

            // 依備份保留政策自動清理最舊備份
            await PruneOldBackupsAsync(serverName, cancellationToken).ConfigureAwait(false);

            return new ServerBackupInfo(
                FileName: fileInfo.Name,
                FullPath: fileInfo.FullName,
                SizeBytes: fileInfo.Length,
                CreatedAt: fileInfo.CreationTimeUtc);
        }
        catch
        {
            if (File.Exists(tempZipPath))
            {
                File.Delete(tempZipPath);
            }
            throw;
        }
    }

    public async Task<bool> RestoreBackupAsync(string serverName, string backupFileName, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(backupFileName);
        cancellationToken.ThrowIfCancellationRequested();

        string serverDir = GetServerDirectory(serverName);
        string backupsDir = GetBackupsDirectory(serverName);
        string backupFilePath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (!File.Exists(backupFilePath))
        {
            return false;
        }

        string stagingDir = Path.Combine(_resolvedServersRoot, $".restore-staging-{Guid.NewGuid():N}");
        string rollbackDir = Path.Combine(_resolvedServersRoot, $".restore-rollback-{Guid.NewGuid():N}");

        try
        {
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

            // 還原成功後清理 rollback 快照與 staging 暫存目錄
            CleanDirectorySafe(rollbackDir);
            CleanDirectorySafe(stagingDir);
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

    public Task<bool> DeleteBackupAsync(string serverName, string backupFileName, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(backupFileName);
        cancellationToken.ThrowIfCancellationRequested();

        string backupsDir = GetBackupsDirectory(serverName);
        string targetPath = Path.Combine(backupsDir, Path.GetFileName(backupFileName));

        if (File.Exists(targetPath))
        {
            File.Delete(targetPath);
            return Task.FromResult(true);
        }

        return Task.FromResult(false);
    }

    private async Task PruneOldBackupsAsync(string serverName, CancellationToken cancellationToken)
    {
        var existing = await ListBackupsAsync(serverName, cancellationToken).ConfigureAwait(false);
        if (existing.Count <= _maxRetentionCount)
        {
            return;
        }

        var toRemove = existing.Skip(_maxRetentionCount).ToList();
        foreach (var backup in toRemove)
        {
            await DeleteBackupAsync(serverName, backup.FileName, cancellationToken).ConfigureAwait(false);
        }
    }

    private string GetServerDirectory(string serverName) =>
        SafeFileSystem.ResolveStableDirectory(Path.Combine(_resolvedServersRoot, serverName));

    private string GetBackupsDirectory(string serverName) =>
        Path.Combine(GetServerDirectory(serverName), "backups");

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
}
