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

        if (File.Exists(dstFile) && !File.Exists(srcFile))
        {
            return Task.FromResult(LocalModMutationResult.Success($"模組已處於{action}狀態", dstFile));
        }

        if (File.Exists(dstFile) && File.Exists(srcFile))
        {
            string srcHash = new HashCalculator().ComputeFileHash(srcFile, "sha256");
            string dstHash = new HashCalculator().ComputeFileHash(dstFile, "sha256");
            if (!string.IsNullOrEmpty(srcHash) && string.Equals(srcHash, dstHash, StringComparison.OrdinalIgnoreCase))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, srcFile);
                return Task.FromResult(LocalModMutationResult.Success($"模組已處於{action}狀態並已清理重複檔案", dstFile));
            }

            string bakFile = Path.Combine(stableModsDir, $"{cleanModId}.conflict.bak");
            if (File.Exists(bakFile))
            {
                bakFile = Path.Combine(stableModsDir, $"{cleanModId}.conflict.{DateTimeOffset.UtcNow.ToUnixTimeSeconds()}.bak");
            }
            SafeFileSystem.MoveWithin(stableModsDir, srcFile, bakFile);
            return Task.FromResult(LocalModMutationResult.Success($"偵測到衝突檔案，已改名保留備份：{Path.GetFileName(bakFile)}", bakFile));
        }

        if (File.Exists(srcFile))
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
            if (File.Exists(enabledPath))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, enabledPath);
                deleted = true;
            }
            else if (File.Exists(disabledPath))
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

        if (!File.Exists(sourceFilePath))
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

        File.Copy(sourceFilePath, targetPath, overwrite: true);
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
        string stagingDir = Path.Combine(stableModsDir, ".download_staging");
        SafeFileSystem.ResolveStableDirectory(stagingDir, create: true);

        string tempFilePath = Path.Combine(stagingDir, $"{safeFileName}.{Guid.NewGuid():N}.tmp");
        string finalTargetPath = Path.Combine(stableModsDir, safeFileName);
        string? backupFilePath = null;

        try
        {
            // 下載
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
                cancellationToken: cancellationToken).ConfigureAwait(false);

            if (!downloadResult.Success)
            {
                Rollback(stagingDir, tempFilePath, finalTargetPath, backupFilePath);
                return ModFileOperationResult.Fail($"下載失敗：{downloadResult.Error}", false);
            }

            // 雜湊校驗
            if (!string.IsNullOrEmpty(expectedHash))
            {
                string algo = !string.IsNullOrEmpty(hashAlgorithm) ? hashAlgorithm : "sha512";
                string actualHash = new HashCalculator().ComputeFileHash(tempFilePath, algo);
                if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                {
                    SafeFileSystem.DeleteWithin(stagingDir, tempFilePath);
                    return ModFileOperationResult.Fail($"檔案雜湊校驗失敗 (預期: {expectedHash}, 實際: {actualHash})", false);
                }
            }

            // 備份舊檔案（若存在）
            if (File.Exists(finalTargetPath))
            {
                backupFilePath = Path.Combine(stagingDir, $"{safeFileName}.bak");
                SafeFileSystem.MoveWithin(stagingDir, finalTargetPath, backupFilePath);
            }

            // 移動新檔案至目標路徑
            SafeFileSystem.MoveWithin(stableModsDir, tempFilePath, finalTargetPath);

            // 清理備份
            if (backupFilePath is not null && File.Exists(backupFilePath))
            {
                SafeFileSystem.DeleteWithin(stagingDir, backupFilePath);
            }

            return ModFileOperationResult.Success(finalTargetPath, "安裝成功");
        }
        catch (OperationCanceledException)
        {
            Rollback(stagingDir, tempFilePath, finalTargetPath, backupFilePath);
            return ModFileOperationResult.Cancel("已取消安裝", rollbackPerformed: true);
        }
        catch (Exception ex)
        {
            Rollback(stagingDir, tempFilePath, finalTargetPath, backupFilePath);
            return ModFileOperationResult.Fail($"安裝失敗：{ex.Message}", true);
        }
    }

    private static void Rollback(string stagingDir, string tempPath, string targetPath, string? backupPath)
    {
        try
        {
            if (File.Exists(tempPath))
            {
                SafeFileSystem.DeleteWithin(stagingDir, tempPath);
            }
            if (backupPath is not null && File.Exists(backupPath))
            {
                SafeFileSystem.MoveWithin(stagingDir, backupPath, targetPath);
            }
        }
        catch
        {
        }
    }

    private static (string EnabledPath, string DisabledPath) ResolveModFilePaths(string stableModsDir, string modId)
    {
        string cleanModId = Path.GetFileName(modId.Trim());
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

        if (File.Exists(enabledPath) || File.Exists(disabledPath))
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
}
