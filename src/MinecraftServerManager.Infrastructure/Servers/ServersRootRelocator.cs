using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器根目錄遷移：驗證、搬移、失敗回復與登錄檔路徑更新</summary>
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
            var entries = SafeFileSystem.ListBoundedDirectory(normalized, maxEntries: 100);
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

        var entries = SafeFileSystem.ListBoundedDirectory(normalized, maxEntries: 10);
        return entries.Count == 0;
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

        SafeFileSystem.ResolveStableDirectory(dstRoot, create: true);
        if (!SafeFileSystem.DirectoryExists(srcRoot))
        {
            return [];
        }

        var entries = SafeFileSystem.ListBoundedDirectory(srcRoot);
        if (entries.Count == 0)
        {
            return [];
        }

        var movedItems = new List<(string DestPath, string SourcePath, bool IsDirectory)>(entries.Count);
        var leftovers = new List<string>();

        try
        {
            for (int i = 0; i < entries.Count; i++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var entry = entries[i];
                string name = Path.GetFileName(entry.FullPath);
                string destPath = Path.Combine(dstRoot, name);

                int pct = (int)(i * 90.0 / entries.Count);
                progress?.Report((Math.Clamp(pct, 5, 90), $"正在搬移：{name}..."));

                if (!MoveEntryWithCrossVolumeSupport(entry.FullPath, destPath, entry.IsDirectory, cancellationToken))
                {
                    leftovers.Add(entry.FullPath);
                }

                movedItems.Add((destPath, entry.FullPath, entry.IsDirectory));
            }

            progress?.Report((95, "正在更新伺服器路徑登錄檔..."));
            RewriteRegistryPaths(dstRoot, srcRoot, dstRoot);
            progress?.Report((100, "資料遷移完成！"));

            Logger.Information("已將伺服器根目錄全部內容從 {OldRoot} 遷移至 {NewRoot}（共 {Count} 項，原位置殘留 {Leftover} 項）", srcRoot, dstRoot, movedItems.Count, leftovers.Count);
            TryDeleteEmptySourceRoot(srcRoot);
            return leftovers;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "遷移伺服器根目錄失敗，開始復原已搬移項目");
            for (int i = movedItems.Count - 1; i >= 0; i--)
            {
                var (DestPath, SourcePath, IsDirectory) = movedItems[i];
                if (leftovers.Contains(SourcePath))
                {
                    // 原位置已半刪且仍被占用，搬回會覆寫失敗；完整副本留在新位置
                    Logger.Warning("項目無法復原至原位置，完整副本保留於: {DestPath}", DestPath);
                    continue;
                }

                try
                {
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

            throw;
        }
    }

    /// <summary>原根目錄已空則刪除</summary>
    private static void TryDeleteEmptySourceRoot(string srcRoot)
    {
        try
        {
            if (!SafeFileSystem.DirectoryExists(srcRoot) || SafeFileSystem.ListBoundedDirectory(srcRoot, maxEntries: 1).Count > 0)
            {
                return;
            }

            SafeFileSystem.DeleteDirectory(srcRoot);
            Logger.Information("原伺服器根目錄已清空並刪除: {OldRoot}", srcRoot);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "刪除已清空的原伺服器根目錄失敗，予以保留: {Path}", srcRoot);
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
            catch (IOException ex)
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
            var loaded = JsonCodec.ReadFile<Dictionary<string, ServerConfigPayload>>(registryPath);
            if (loaded is null || loaded.Count == 0)
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
