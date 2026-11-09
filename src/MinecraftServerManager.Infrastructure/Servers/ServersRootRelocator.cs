using System.Text;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器存放根目錄遷移目標路徑檢查結果
/// </summary>
public enum RelocationPathCheckResult
{
    Valid,
    EmptyTarget,
    TargetIsFile,
    SameAsCurrent,
    SubdirectoryOfCurrent,
}

/// <summary>
/// 負責伺服器存放根目錄變更時之路徑驗證、既有內容探測、全量資料遷移、跨磁碟區搬移、失敗回滾與註冊表路徑更新。
/// </summary>
public static class ServersRootRelocator
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServersRootRelocator));

    /// <summary>
    /// 驗證新設定之伺服器存放根目錄是否合法。
    /// </summary>
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

    /// <summary>
    /// 檢查原伺服器根目錄是否存放有伺服器或檔案（若僅有空的 servers.json 視為無存放資料）。
    /// </summary>
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
                string.Equals(Path.GetFileName(entries[0].FullPath), "servers.json", StringComparison.OrdinalIgnoreCase))
            {
                string json = SafeFileSystem.ReadAllText(entries[0].FullPath, Encoding.UTF8);
                var registry = JsonCodec.Deserialize<Dictionary<string, ServerConfigPayload>>(json);
                return registry is { Count: > 0 };
            }

            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "檢查原伺服器根目錄內容時發生例外，保守視為有內容: {0}", normalized);
            return true;
        }
    }

    /// <summary>
    /// 檢查目標目錄是否為空資料夾（或尚不存在）。
    /// </summary>
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

    /// <summary>
    /// 將舊根目錄內的所有內容遷移至新根目錄，並同步更新 servers.json 內的伺服器路徑。
    /// 若中途失敗則自動將已搬移項目復原回舊根目錄。
    /// </summary>
    public static void RelocateAllContent(
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
            return;
        }

        var entries = SafeFileSystem.ListBoundedDirectory(srcRoot);
        if (entries.Count == 0)
        {
            return;
        }

        var movedItems = new List<(string DestPath, string SourcePath, bool IsDirectory)>(entries.Count);

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

                MoveEntryWithCrossVolumeSupport(entry.FullPath, destPath, entry.IsDirectory);
                movedItems.Add((destPath, entry.FullPath, entry.IsDirectory));
            }

            progress?.Report((95, "正在更新伺服器路徑註冊表..."));
            RewriteRegistryPaths(dstRoot, srcRoot, dstRoot);
            progress?.Report((100, "資料遷移完成！"));

            Logger.Information("已將伺服器根目錄全部內容從 {OldRoot} 遷移至 {NewRoot}（共 {Count} 項）", srcRoot, dstRoot, movedItems.Count);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "遷移伺服器根目錄失敗，開始復原已搬移項目: {Message}", ex.Message);
            for (int i = movedItems.Count - 1; i >= 0; i--)
            {
                var (DestPath, SourcePath, IsDirectory) = movedItems[i];
                try
                {
                    if (IsDirectory ? SafeFileSystem.DirectoryExists(DestPath) : SafeFileSystem.FileExists(DestPath))
                    {
                        MoveEntryWithCrossVolumeSupport(DestPath, SourcePath, IsDirectory);
                    }
                }
                catch (Exception rollbackEx) when (rollbackEx is not OperationCanceledException)
                {
                    Logger.Warning(rollbackEx, "復原搬移項目失敗: {0} -> {1}", DestPath, SourcePath);
                }
            }

            throw;
        }
    }

    private static void MoveEntryWithCrossVolumeSupport(string sourcePath, string destinationPath, bool isDirectory)
    {
        if (!isDirectory)
        {
            SafeFileSystem.MovePath(sourcePath, destinationPath, overwrite: true);
            return;
        }

        string? srcRoot = Path.GetPathRoot(sourcePath);
        string? dstRoot = Path.GetPathRoot(destinationPath);
        bool sameVolume = string.Equals(srcRoot, dstRoot, StringComparison.OrdinalIgnoreCase);

        if (sameVolume)
        {
            try
            {
                SafeFileSystem.MovePath(sourcePath, destinationPath, overwrite: false);
                return;
            }
            catch (IOException ex)
            {
                Logger.Warning("同磁碟目錄直接移動失敗，改用複製後刪除 ({0}): {1}", sourcePath, ex.Message);
            }
        }

        SafeFileSystem.CopyDirectoryTreeSafe(sourcePath, destinationPath);
        SafeFileSystem.DeleteDirectory(sourcePath, recursive: true);
    }

    private static void RewriteRegistryPaths(string registryDirectory, string oldRoot, string newRoot)
    {
        string registryPath = Path.Combine(registryDirectory, "servers.json");
        if (!SafeFileSystem.FileExists(registryPath))
        {
            return;
        }

        try
        {
            string json = SafeFileSystem.ReadAllText(registryPath, Encoding.UTF8);
            var loaded = JsonCodec.Deserialize<Dictionary<string, ServerConfigPayload>>(json);
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

            string outJson = JsonCodec.Serialize(updated, indented: true);
            AtomicFileWriter.WriteText(registryPath, outJson);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "更新遷移後的 servers.json 路徑時發生例外: {0}", registryPath);
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
            Logger.Warning("轉換伺服器相對路徑失敗 ({0}): {1}", originalPath, ex.Message);
        }

        return originalPath;
    }
}
