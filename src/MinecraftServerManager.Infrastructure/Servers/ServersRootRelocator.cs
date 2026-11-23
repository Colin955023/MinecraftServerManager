using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器根目錄遷移：驗證、搬移、失敗回復與伺服器清單檔路徑更新</summary>
public static class ServersRootRelocator
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServersRootRelocator));

    /// <summary>驗證新設定之伺服器存放根目錄是否合法</summary>
    public static RelocationPathCheckResult ValidateTargetRoot(
        string? currentRoot,
        string? newRoot,
        out string normalizedCurrent,
        out string normalizedNew)
    {
        normalizedCurrent = SettingsManager.NormalizeExactServersRootPath(currentRoot);
        normalizedNew = SettingsManager.NormalizeServersRootPath(newRoot);

        if (string.IsNullOrWhiteSpace(normalizedNew))
        {
            return RelocationPathCheckResult.EmptyTarget;
        }

        if (SafeFileSystem.FileExists(normalizedNew))
        {
            return RelocationPathCheckResult.TargetIsFile;
        }

        if (!string.IsNullOrWhiteSpace(normalizedCurrent))
        {
            if (string.Equals(normalizedCurrent, normalizedNew, StringComparison.OrdinalIgnoreCase))
            {
                return RelocationPathCheckResult.SameAsCurrent;
            }

            if (normalizedNew.StartsWith(Path.TrimEndingDirectorySeparator(normalizedCurrent) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || (SafeFileSystem.DirectoryExists(normalizedCurrent) && SafeFileSystem.IsPathWithin(normalizedCurrent, normalizedNew, strict: false)))
            {
                return RelocationPathCheckResult.SubdirectoryOfCurrent;
            }
        }

        return RelocationPathCheckResult.Valid;
    }

    /// <summary>原根目錄是否有資料（只有空的 servers.json 視為無）</summary>
    public static bool HasStoredContent(string? currentRoot)
    {
        string normalized = SettingsManager.NormalizeExactServersRootPath(currentRoot);
        if (string.IsNullOrWhiteSpace(normalized) || !SafeFileSystem.DirectoryExists(normalized))
        {
            return false;
        }

        try
        {
            var entries = SafeFileSystem.ListBoundedDirectory(normalized);
            if (entries.Count == 0)
            {
                return false;
            }

            if (entries.Count == 1 &&
                !entries[0].IsDirectory &&
                string.Equals(Path.GetFileName(entries[0].FullPath), ServerDefaults.RegistryFileName, StringComparison.OrdinalIgnoreCase))
            {
                var registry = JsonCodec.ReadFile<Dictionary<string, ServerConfigPayload>>(entries[0].FullPath);
                return registry is { Count: > 0 };
            }

            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "檢查原伺服器根目錄內容時發生例外，保守視為有內容: {Path}", normalized);
            return true;
        }
    }

    /// <summary>目標目錄是否為空資料夾（或尚不存在）</summary>
    public static bool IsTargetDirectoryEmpty(string? targetRoot)
    {
        string normalized = SettingsManager.NormalizeExactServersRootPath(targetRoot);
        if (string.IsNullOrWhiteSpace(normalized) || !SafeFileSystem.DirectoryExists(normalized))
        {
            return true;
        }

        return SafeFileSystem.IsDirectoryEmpty(normalized);
    }

    /// <summary>遷移全部內容並更新 servers.json；失敗時復原。回傳已複製到新位置但原位置刪不掉的項目路徑</summary>
    public static IReadOnlyList<string> RelocateAllContent(
        string currentRoot,
        string newRoot,
        IProgress<(int Percent, string Message)>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var check = ValidateTargetRoot(currentRoot, newRoot, out string srcRoot, out string dstRoot);
        if (check != RelocationPathCheckResult.Valid)
        {
            throw new InvalidOperationException($"目標路徑驗證失敗：{check}");
        }

        if (!IsTargetDirectoryEmpty(dstRoot))
        {
            throw new InvalidOperationException("目標資料夾不是空的，無法遷移資料。");
        }

        bool createdTargetRoot = !SafeFileSystem.DirectoryExists(dstRoot);
        if (!SafeFileSystem.DirectoryExists(srcRoot))
        {
            SafeFileSystem.ResolveStableDirectory(dstRoot, create: true);
            return [];
        }

        var entries = SafeFileSystem.ListBoundedDirectory(srcRoot);
        EnsureCrossVolumeFreeSpace(srcRoot, dstRoot);
        SafeFileSystem.ResolveStableDirectory(dstRoot, create: true);
        if (entries.Count == 0)
        {
            return [];
        }

        var movedItems = new List<(string DestPath, string SourcePath, bool IsDirectory)>(entries.Count);
        var leftovers = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        try
        {
            for (int i = 0; i < entries.Count; i++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var entry = entries[i];
                string name = Path.GetFileName(entry.FullPath);
                string destPath = Path.Combine(dstRoot, name);

                int pct = ProgressMapping.Map(i, entries.Count, 5, 90);
                progress?.Report((pct, $"正在搬移：{name}..."));

                if (!MoveEntryWithCrossVolumeSupport(entry.FullPath, destPath, entry.IsDirectory, cancellationToken))
                {
                    leftovers.Add(entry.FullPath);
                }

                movedItems.Add((destPath, entry.FullPath, entry.IsDirectory));
            }

            progress?.Report((95, "正在更新伺服器清單檔路徑..."));
            RewriteRegistryPaths(dstRoot, srcRoot, dstRoot);
            progress?.Report((100, "資料遷移完成！"));

            Logger.Information("已將伺服器根目錄全部內容從 {OldRoot} 遷移至 {NewRoot}（共 {Count} 項，原位置殘留 {Leftover} 項）", srcRoot, dstRoot, movedItems.Count, leftovers.Count);
            TryDeleteEmptySourceRoot(srcRoot);
            return [.. leftovers];
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "遷移伺服器根目錄失敗，開始復原已搬移項目");
            for (int i = movedItems.Count - 1; i >= 0; i--)
            {
                var (DestPath, SourcePath, IsDirectory) = movedItems[i];
                try
                {
                    if (leftovers.Contains(SourcePath))
                    {
                        // 原位置已半刪且仍被占用，不能整個搬回；只補回已被刪除的檔案
                        RestoreLeftoverDirectory(DestPath, SourcePath);
                        continue;
                    }

                    if (IsDirectory ? SafeFileSystem.DirectoryExists(DestPath) : SafeFileSystem.FileExists(DestPath))
                    {
                        // 復原不可沿用可能已取消的權杖，否則跨磁碟項目會留在新位置
                        MoveEntryWithCrossVolumeSupport(DestPath, SourcePath, IsDirectory, CancellationToken.None);
                    }
                }
                catch (Exception rollbackEx) when (rollbackEx is not OperationCanceledException)
                {
                    Logger.Warning(rollbackEx, "復原搬移項目失敗: {DestPath} -> {SourcePath}", DestPath, SourcePath);
                }
            }

            if (createdTargetRoot)
            {
                TryDeleteEmptyDirectory(dstRoot, "遷移失敗後新建的目標資料夾");
            }

            throw;
        }
    }

    /// <summary>跨磁碟遷移前確認目標磁碟可容納來源全部內容；無法估算時記錄警告並交由實際複製判定</summary>
    private static void EnsureCrossVolumeFreeSpace(string srcRoot, string dstRoot)
    {
        if (string.Equals(Path.GetPathRoot(srcRoot), Path.GetPathRoot(dstRoot), StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        long requiredBytes;
        try
        {
            requiredBytes = SafeFileSystem.EnumerateBoundedTree(srcRoot, rejectReparse: false)
                .Where(static e => !e.IsDirectory)
                .Sum(static e => e.Length);
        }
        catch (SafeFileSystemException ex) when (ex.IsLimitExceeded)
        {
            Logger.Warning(ex, "原伺服器根目錄超出估算上限，略過遷移前空間檢查: {Path}", srcRoot);
            return;
        }

        if (ServerSetupHelpers.CheckFreeSpace(dstRoot, requiredBytes) is { } error)
        {
            throw new IOException(error);
        }
    }

    /// <summary>將新位置的完整副本補回半刪的原目錄（已存在者不覆寫），完成後刪除新位置</summary>
    private static void RestoreLeftoverDirectory(string destPath, string sourcePath)
    {
        if (!SafeFileSystem.DirectoryExists(destPath))
        {
            return;
        }

        foreach (var entry in SafeFileSystem.EnumerateBoundedTree(destPath, rejectReparse: true).ToList())
        {
            string target = Path.Combine(sourcePath, Path.GetRelativePath(destPath, entry.FullPath));
            if (entry.IsDirectory)
            {
                SafeFileSystem.ResolveStableDirectory(target, create: true);
            }
            else if (!SafeFileSystem.FileExists(target))
            {
                SafeFileSystem.CopyFile(entry.FullPath, target, overwrite: false);
            }
        }

        SafeFileSystem.DeleteDirectory(destPath, recursive: true);
    }

    /// <summary>原根目錄已空則刪除</summary>
    private static void TryDeleteEmptySourceRoot(string srcRoot)
    {
        if (TryDeleteEmptyDirectory(srcRoot, "已清空的原伺服器根目錄"))
        {
            Logger.Information("原伺服器根目錄已清空並刪除: {OldRoot}", srcRoot);
        }
    }

    /// <summary>目錄存在且為空則刪除；失敗記錄警告</summary>
    private static bool TryDeleteEmptyDirectory(string directory, string purpose)
    {
        try
        {
            if (!SafeFileSystem.DirectoryExists(directory) || !SafeFileSystem.IsDirectoryEmpty(directory))
            {
                return false;
            }

            SafeFileSystem.DeleteDirectory(directory);
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "刪除空資料夾失敗，予以保留（{Purpose}）: {Path}", purpose, directory);
            return false;
        }
    }

    /// <summary>搬移項目；回傳 false 代表新位置已完整，但原位置刪除失敗而殘留</summary>
    private static bool MoveEntryWithCrossVolumeSupport(string sourcePath, string destinationPath, bool isDirectory, CancellationToken cancellationToken = default)
    {
        if (!isDirectory)
        {
            SafeFileSystem.MovePath(sourcePath, destinationPath, overwrite: true);
            return true;
        }

        string? srcRoot = Path.GetPathRoot(sourcePath);
        string? dstRoot = Path.GetPathRoot(destinationPath);
        bool sameVolume = string.Equals(srcRoot, dstRoot, StringComparison.OrdinalIgnoreCase);

        if (sameVolume)
        {
            try
            {
                SafeFileSystem.MovePath(sourcePath, destinationPath, overwrite: false);
                return true;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning(ex, "同磁碟目錄直接移動失敗，改用複製後刪除 ({SourcePath})", sourcePath);
            }
        }

        try
        {
            SafeFileSystem.CopyDirectoryTreeSafe(sourcePath, destinationPath, cancellationToken);
        }
        catch (Exception)
        {
            if (SafeFileSystem.DirectoryExists(destinationPath))
            {
                try
                {
                    SafeFileSystem.DeleteDirectory(destinationPath, recursive: true);
                }
                catch (Exception cleanupEx) when (cleanupEx is not OperationCanceledException)
                {
                    Logger.Warning(cleanupEx, "清理未完成的跨磁碟複製目標失敗: {DestinationPath}", destinationPath);
                }
            }
            throw;
        }

        // 新位置已完整：原位置刪不掉（檔案被占用等）不算搬移失敗，否則會留下半刪的來源與指向舊根目錄的登錄
        try
        {
            SafeFileSystem.DeleteDirectory(sourcePath, recursive: true);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "已複製至新位置，但原位置刪除失敗而殘留: {SourcePath}", sourcePath);
            return false;
        }
    }

    private static void RewriteRegistryPaths(string registryDirectory, string oldRoot, string newRoot)
    {
        string registryPath = Path.Combine(registryDirectory, ServerDefaults.RegistryFileName);
        if (!SafeFileSystem.FileExists(registryPath))
        {
            return;
        }

        try
        {
            // 無法解析時擲錯觸發回滾，避免新根目錄留下仍指向舊位置的清單
            var loaded = JsonCodec.ReadFile<Dictionary<string, ServerConfigPayload>>(registryPath)
                ?? throw new InvalidDataException($"無法解析伺服器清單檔：{registryPath}");
            if (loaded.Count == 0)
            {
                return;
            }

            var updated = new Dictionary<string, ServerConfigPayload>(loaded.Count, StringComparer.OrdinalIgnoreCase);
            foreach (var (key, payload) in loaded)
            {
                string updatedServerPath = RelocatePathPrefix(payload.Path, oldRoot, newRoot, Path.Combine(newRoot, payload.Name));
                string updatedBackupPath = !string.IsNullOrWhiteSpace(payload.BackupPath) &&
                                           SafeFileSystem.IsPathWithin(oldRoot, payload.BackupPath, strict: false)
                    ? RelocatePathPrefix(payload.BackupPath, oldRoot, newRoot, payload.BackupPath)
                    : payload.BackupPath;

                updated[key] = payload with
                {
                    Path = updatedServerPath,
                    BackupPath = updatedBackupPath,
                };
            }

            AtomicFileWriter.WriteJsonOrThrow(registryPath, updated);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "更新遷移後的 servers.json 路徑時發生例外: {RegistryPath}", registryPath);
            throw;
        }
    }

    private static string RelocatePathPrefix(string? originalPath, string oldRoot, string newRoot, string fallbackPath)
    {
        if (string.IsNullOrWhiteSpace(originalPath))
        {
            return fallbackPath;
        }

        try
        {
            if (SafeFileSystem.IsPathWithin(oldRoot, originalPath, strict: false))
            {
                string relative = Path.GetRelativePath(oldRoot, originalPath);
                return Path.GetFullPath(Path.Combine(newRoot, relative));
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "轉換伺服器相對路徑失敗 ({OriginalPath})", originalPath);
        }

        return originalPath;
    }
}
