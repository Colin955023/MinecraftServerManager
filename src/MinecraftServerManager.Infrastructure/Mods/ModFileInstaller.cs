using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組檔案異動、啟停、批次刪除與原子交易安裝實作
/// </summary>
public sealed class ModFileInstaller(IHttpPort httpPort) : IModFileInstaller
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ModFileInstaller");
    public Task<LocalModMutationResult> SetModStateAsync(
        string modsDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(modId);
        cancellationToken.ThrowIfCancellationRequested();

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        var (enabledFile, disabledFile) = ResolveModFilePaths(stableModsDir, modId);
        string cleanModId = Path.GetFileNameWithoutExtension(enabledFile);

        string srcFile = enable ? disabledFile : enabledFile;
        string dstFile = enable ? enabledFile : disabledFile;
        string action = enable ? "啟用" : "停用";

        if (SafeFileSystem.FileExists(dstFile) && !SafeFileSystem.FileExists(srcFile))
        {
            return Task.FromResult(LocalModMutationResult.Success($"模組已處於{action}狀態", dstFile));
        }

        if (SafeFileSystem.FileExists(dstFile) && SafeFileSystem.FileExists(srcFile))
        {
            if (SafeFileSystem.GetFileLength(srcFile) == SafeFileSystem.GetFileLength(dstFile) && HasSameContent(srcFile, dstFile))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, srcFile);
                return Task.FromResult(LocalModMutationResult.Success($"模組已處於{action}狀態並已清理重複檔案", dstFile));
            }

            string bakFile = Path.Combine(stableModsDir, $"{cleanModId}.conflict.bak");
            if (SafeFileSystem.FileExists(bakFile))
            {
                bakFile = Path.Combine(stableModsDir, $"{cleanModId}.conflict.{DateTimeOffset.UtcNow.ToUnixTimeSeconds()}.bak");
            }
            SafeFileSystem.MoveWithin(stableModsDir, srcFile, bakFile);
            return Task.FromResult(LocalModMutationResult.Success($"偵測到衝突檔案，已改名保留備份：{Path.GetFileName(bakFile)}", bakFile));
        }

        if (SafeFileSystem.FileExists(srcFile))
        {
            SafeFileSystem.MoveWithin(stableModsDir, srcFile, dstFile);
            return Task.FromResult(LocalModMutationResult.Success($"已成功{action}模組：{Path.GetFileName(dstFile)}", dstFile));
        }

        return Task.FromResult(LocalModMutationResult.Failure($"{action}失敗", $"找不到模組檔案：{Path.GetFileName(srcFile)}", [cleanModId]));
    }

    public Task<LocalModMutationResult> DeleteModsAsync(
        string modsDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        if (modIds is null || modIds.Count == 0)
        {
            return Task.FromResult(LocalModMutationResult.Failure("刪除失敗", "沒有可刪除的模組清單"));
        }

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        int deletedCount = 0;
        var missingIds = new List<string>();

        foreach (string modId in modIds)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var (enabledPath, disabledPath) = ResolveModFilePaths(stableModsDir, modId);
            string cleanModId = Path.GetFileNameWithoutExtension(enabledPath);

            bool deleted = false;
            if (SafeFileSystem.FileExists(enabledPath))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, enabledPath);
                deleted = true;
            }
            else if (SafeFileSystem.FileExists(disabledPath))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, disabledPath);
                deleted = true;
            }

            if (deleted)
            {
                deletedCount++;
            }
            else
            {
                missingIds.Add(cleanModId);
            }
        }

        if (deletedCount > 0 && missingIds.Count == 0)
        {
            return Task.FromResult(LocalModMutationResult.Success($"已成功刪除 {deletedCount} 個模組檔案", affectedCount: deletedCount));
        }

        if (deletedCount > 0)
        {
            return Task.FromResult(new LocalModMutationResult("partial", "部分刪除成功", $"已刪除 {deletedCount} 個模組，但有 {missingIds.Count} 個未找到", null, deletedCount, missingIds));
        }

        return Task.FromResult(LocalModMutationResult.Failure("刪除失敗", "找不到任何可刪除的模組檔案", missingIds));
    }

    public Task<LocalModMutationResult> ImportLocalModAsync(
        string modsDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceFilePath);
        cancellationToken.ThrowIfCancellationRequested();

        if (!SafeFileSystem.FileExists(sourceFilePath))
        {
            return Task.FromResult(LocalModMutationResult.Failure("匯入失敗", $"來源檔案不存在：{sourceFilePath}"));
        }

        string fileName = Path.GetFileName(sourceFilePath);
        if (!fileName.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
        {
            return Task.FromResult(LocalModMutationResult.Failure("匯入失敗", "僅支援 .jar 格式模組檔案"));
        }

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        string targetPath = Path.Combine(stableModsDir, fileName);
        if (!SafeFileSystem.IsPathWithin(stableModsDir, targetPath, strict: false))
        {
            return Task.FromResult(LocalModMutationResult.Failure("匯入失敗", "目標路徑超出模組資料夾邊界"));
        }

        SafeFileSystem.CopyFile(sourceFilePath, targetPath, overwrite: true);
        return Task.FromResult(LocalModMutationResult.Success($"模組「{fileName}」已成功匯入", targetPath));
    }

    public async Task<ModFileOperationResult> InstallRemoteModAsync(
        string modsDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(downloadUrl);
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        cancellationToken.ThrowIfCancellationRequested();

        string safeFileName = Path.GetFileName(fileName);
        if (!safeFileName.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
        {
            return ModFileOperationResult.Fail("僅支援 .jar 格式模組檔案", false);
        }

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        string stagingRoot = Path.Combine(stableModsDir, ".download_staging");
        SafeFileSystem.ResolveStableDirectory(stagingRoot, create: true);
        string stagingDir = Path.Combine(stagingRoot, Guid.NewGuid().ToString("N"));
        SafeFileSystem.ResolveStableDirectory(stagingDir, create: true);

        string tempFilePath = Path.Combine(stagingDir, $"{safeFileName}.{Guid.NewGuid():N}.tmp");
        string finalTargetPath = Path.Combine(stableModsDir, safeFileName);
        string? backupFilePath = null;
        string algo = !string.IsNullOrEmpty(hashAlgorithm) ? hashAlgorithm : "sha512";

        try
        {
            // 下載並於串流管線中即時增量校驗雜湊（消除下載後二次全檔磁碟讀取 I/O）
            var downloadResult = await httpPort.DownloadAsync(
                new Uri(downloadUrl),
                tempFilePath,
                progress: progress is not null ? new Progress<HttpProgress>(p =>
                {
                    if (p.TotalBytes > 0)
                    {
                        progress.Report((int)((double)p.BytesDownloaded / p.TotalBytes * 100));
                    }
                }) : null,
                expectedHash: !string.IsNullOrEmpty(expectedHash) ? expectedHash : null,
                expectedHashAlgorithm: algo,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            if (!downloadResult.Success)
            {
                Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
                return ModFileOperationResult.Fail($"下載或雜湊校驗失敗：{downloadResult.Error}", false);
            }

            // 備份舊檔案（若存在）
            if (SafeFileSystem.FileExists(finalTargetPath))
            {
                backupFilePath = Path.Combine(stagingDir, $"{safeFileName}.bak");
                if (!SafeFileSystem.MoveWithin(stableModsDir, finalTargetPath, backupFilePath))
                {
                    backupFilePath = null;
                    Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
                    return ModFileOperationResult.Fail("無法備份既有模組檔案", false);
                }
            }

            // 移動新檔案至目標路徑
            if (!SafeFileSystem.MoveWithin(stableModsDir, tempFilePath, finalTargetPath))
            {
                Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
                return ModFileOperationResult.Fail("無法移動模組檔案至目標位置", true);
            }

            // 清理備份
            if (backupFilePath is not null && SafeFileSystem.FileExists(backupFilePath))
            {
                SafeFileSystem.DeleteWithin(stagingDir, backupFilePath);
            }

            return ModFileOperationResult.Success(finalTargetPath, "安裝成功");
        }
        catch (OperationCanceledException)
        {
            Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
            return ModFileOperationResult.Cancel("已取消安裝", rollbackPerformed: true);
        }
        catch (Exception ex)
        {
            Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
            return ModFileOperationResult.Fail($"安裝失敗：{ex.Message}", true);
        }
        finally
        {
            TryCleanupStagingDir(stableModsDir, stagingDir);
        }
    }

    /// <summary>
    /// 清理模組目錄中的 .download_staging 暫存資料夾
    /// </summary>
    public static void CleanupStagingDirectory(string modsDirectory)
    {
        try
        {
            string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory);
            string stagingDir = Path.Combine(stableModsDir, ".download_staging");
            if (SafeFileSystem.DirectoryExists(stagingDir))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, stagingDir);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("清理模組暫存目錄失敗: {0}", ex.Message);
        }
    }

    private static void TryCleanupStagingDir(string stableModsDir, string stagingDir)
    {
        try
        {
            if (SafeFileSystem.DirectoryExists(stagingDir))
            {
                var entries = SafeFileSystem.ListBoundedDirectory(stagingDir, maxEntries: 10, rejectReparse: false);
                if (entries.Count == 0)
                {
                    SafeFileSystem.DeleteWithin(stableModsDir, stagingDir);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("清理暫存子目錄失敗: {0}", ex.Message);
        }
    }

    private static void Rollback(string stableModsDir, string tempPath, string targetPath, string? backupPath)
    {
        try
        {
            if (SafeFileSystem.FileExists(tempPath))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, tempPath);
            }
            if (backupPath is not null && SafeFileSystem.FileExists(backupPath))
            {
                SafeFileSystem.MoveWithin(stableModsDir, backupPath, targetPath);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "模組安裝復原（Rollback）失敗");
        }
    }

    private static (string EnabledPath, string DisabledPath) ResolveModFilePaths(string stableModsDir, string modId)
    {
        string raw = modId.Trim();
        int hashIdx = raw.IndexOf('#');
        if (hashIdx >= 0)
        {
            raw = raw[..hashIdx];
        }
        string cleanModId = Path.GetFileName(raw.Trim('\'', '"', ' ', '\r', '\n', '\t'));
        if (cleanModId.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
        {
            cleanModId = cleanModId[..^4];
        }
        else if (cleanModId.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase))
        {
            cleanModId = cleanModId[..^13];
        }

        string enabledPath = Path.Combine(stableModsDir, $"{cleanModId}.jar");
        string disabledPath = Path.Combine(stableModsDir, $"{cleanModId}.jar.disabled");

        if (SafeFileSystem.FileExists(enabledPath) || SafeFileSystem.FileExists(disabledPath))
        {
            return (enabledPath, disabledPath);
        }

        var matched = SafeFileSystem.ListBoundedDirectory(stableModsDir)
            .Where(f => !f.IsDirectory && (f.FullPath.EndsWith(".jar", StringComparison.OrdinalIgnoreCase) || f.FullPath.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase)))
            .FirstOrDefault(f =>
            {
                string fileName = Path.GetFileName(f.FullPath);
                string stem = fileName;
                if (stem.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase))
                {
                    stem = stem[..^13];
                }
                else if (stem.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
                {
                    stem = stem[..^4];
                }

                return string.Equals(stem, cleanModId, StringComparison.OrdinalIgnoreCase)
                    || stem.StartsWith($"{cleanModId}-", StringComparison.OrdinalIgnoreCase)
                    || stem.StartsWith($"{cleanModId}_", StringComparison.OrdinalIgnoreCase);
            });

        if (matched is not null)
        {
            string fileName = Path.GetFileName(matched.FullPath);
            string stem = fileName;
            if (stem.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase))
            {
                stem = stem[..^13];
            }
            else if (stem.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
            {
                stem = stem[..^4];
            }

            return (Path.Combine(stableModsDir, $"{stem}.jar"), Path.Combine(stableModsDir, $"{stem}.jar.disabled"));
        }

        return (enabledPath, disabledPath);
    }

    /// <summary>
    /// 檢查指定的模組下載 URL 是否為官方 Modrinth CDN 來源
    /// </summary>
    public static bool IsOfficialModrinthSource(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return false;
        }

        if (Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            return uri.Scheme == Uri.UriSchemeHttps &&
                   (string.Equals(uri.Host, "cdn.modrinth.com", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(uri.Host, "modrinth.com", StringComparison.OrdinalIgnoreCase));
        }

        return false;
    }

    private static bool HasSameContent(string firstFile, string secondFile)
    {
        string firstHash = HashCalculator.Shared.ComputeFileHash(firstFile, "sha256");
        return !string.IsNullOrEmpty(firstHash)
            && string.Equals(firstHash, HashCalculator.Shared.ComputeFileHash(secondFile, "sha256"), StringComparison.OrdinalIgnoreCase);
    }
}
