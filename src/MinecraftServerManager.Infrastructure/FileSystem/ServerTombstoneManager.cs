using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

/// <summary>伺服器刪除交易暫存目錄（Tombstone）記錄</summary>
public sealed record DeleteTombstoneRecord(
    string ServerName,
    string OriginalPath,
    DateTime Timestamp,
    int SchemaVersion = 1);

/// <summary>伺服器刪除交易暫存與中斷復原管理工具</summary>
public static class ServerTombstoneManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerTombstoneManager));

    private const string DeletePrefix = ServerDefaults.InternalPrefix + "delete-";
    internal const string DeleteMarker = ServerDefaults.InternalPrefix + "delete-marker.json";

    private static readonly string[] EphemeralStagingPrefixes =
    [
        ServerDefaults.InternalPrefix + "create-staging-",
        ServerDefaults.InternalPrefix + "import-staging-",
        ServerDefaults.InternalPrefix + "restore-staging-",
    ];

    private static readonly string[] ProtectedRestorePrefixes =
    [
        ServerDefaults.InternalPrefix + "restore-rollback-",
        ServerDefaults.InternalPrefix + "restore-preserved-logs-",
    ];

    /// <summary>準備伺服器刪除 tombstone 並將目錄安全移入暫存</summary>
    public static (string TombstonePath, string JournalPath) PrepareDeleteTombstone(
        string serversRoot,
        string serverName,
        string originalPath)
    {
        string root = SafeFileSystem.ResolveStableDirectory(serversRoot);
        string original = Path.GetFullPath(originalPath);

        if (!SafeFileSystem.DirectoryExists(original))
        {
            throw new DirectoryNotFoundException($"找不到伺服器目錄： {original}");
        }

        string validatedName = ServerName.Parse(serverName).Value;
        string tombstoneId = Guid.NewGuid().ToString("N");
        string tombstoneName = $"{DeletePrefix}{tombstoneId}";
        string tombstonePath = Path.Combine(root, tombstoneName);
        string journalPath = Path.Combine(root, $"{tombstoneName}.json");

        var record = new DeleteTombstoneRecord(validatedName, original, DateTime.UtcNow);
        byte[] json = JsonCodec.SerializeToUtf8Bytes(record)
            ?? throw new IOException($"無法序列化刪除紀錄： {journalPath}");

        // 寫入外部紀錄
        // 紀錄是當機復原的依據；寫入失敗時不得搬移目錄
        if (!AtomicFileWriter.WriteBytes(journalPath, json))
        {
            throw new IOException($"無法寫入刪除紀錄： {journalPath}");
        }

        // 嚴格在邊界內移動目錄至 tombstone；失敗時清除剛寫入的紀錄，避免留下孤兒 journal
        try
        {
            SafeFileSystem.MoveWithinStrict(root, original, tombstonePath);
        }
        catch (Exception)
        {
            SafeFileSystem.DeleteWithin(root, journalPath);
            throw;
        }

        // 寫入內部標記
        string internalMarker = Path.Combine(tombstonePath, DeleteMarker);
        if (!AtomicFileWriter.WriteBytes(internalMarker, json))
        {
            // 外部紀錄已足以復原，內部標記僅為輔助
            Logger.Warning("寫入刪除標記失敗: {Path}", internalMarker);
        }

        return (tombstonePath, journalPath);
    }

    /// <summary>於啟動時掃描並復原或清理未完成的刪除 tombstone</summary>
    public static void RecoverDeleteTombstones(
        string serversRoot,
        Func<string, string?> registeredServerLookup)
    {
        if (!SafeFileSystem.DirectoryExists(serversRoot))
        {
            return;
        }

        string root = SafeFileSystem.ResolveStableDirectory(serversRoot);
        var entries = SafeFileSystem.ListBoundedDirectory(root, rejectReparse: false);
        var tombstoneNames = entries
            .Where(static entry => entry.IsDirectory)
            .Select(static entry => Path.GetFileName(entry.FullPath))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        foreach (var entry in entries)
        {
            string dirName = Path.GetFileName(entry.FullPath);
            if (!entry.IsDirectory)
            {
                CleanOrphanJournal(root, entry, dirName, tombstoneNames);
                continue;
            }

            if (SafeFileSystem.IsReparsePoint(entry.FullPath))
            {
                continue;
            }

            if (IsMatchingPrefix(dirName, EphemeralStagingPrefixes))
            {
                SafeFileSystem.DeleteWithin(root, entry.FullPath);
                continue;
            }

            if (IsMatchingPrefix(dirName, ProtectedRestorePrefixes))
            {
                Logger.Warning("偵測到未完成還原之保護快照目錄，予以保留供人工檢視: {Path}", entry.FullPath);
                continue;
            }

            if (!dirName.StartsWith(DeletePrefix, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string markerPath = Path.Combine(entry.FullPath, DeleteMarker);
            string journalPath = Path.Combine(root, $"{dirName}.json");

            DeleteTombstoneRecord? record = JsonCodec.TryReadFile<DeleteTombstoneRecord>(markerPath)
                ?? JsonCodec.TryReadFile<DeleteTombstoneRecord>(journalPath);

            if (record == null || record.SchemaVersion != 1 || string.IsNullOrWhiteSpace(record.ServerName))
            {
                // 無法驗證的項目保留以避免誤刪
                Logger.Warning("刪除暫存目錄缺少有效紀錄，予以保留供人工檢視: {Path}", entry.FullPath);
                continue;
            }

            string? registeredPath = registeredServerLookup(record.ServerName);
            if (string.IsNullOrEmpty(registeredPath))
            {
                // 已從登記中移除，確認已提交刪除，執行安全清理
                SafeFileSystem.DeleteWithin(root, entry.FullPath);
                SafeFileSystem.DeleteWithin(root, journalPath);
                continue;
            }

            // 伺服器仍在登記中，代表在提交前異常終止，執行 fail-safe 還原
            string targetOriginal = Path.GetFullPath(registeredPath);
            if (SafeFileSystem.DirectoryExists(targetOriginal))
            {
                // 原目錄已存在，保留暫存目錄以避免覆蓋
                Logger.Warning("原伺服器目錄 {OriginalPath} 已存在，保留刪除暫存目錄: {Path}", targetOriginal, entry.FullPath);
                continue;
            }

            try
            {
                SafeFileSystem.MoveWithinStrict(root, entry.FullPath, targetOriginal);
                SafeFileSystem.DeleteWithin(targetOriginal, Path.Combine(targetOriginal, DeleteMarker));
                SafeFileSystem.DeleteWithin(root, journalPath);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "還原伺服器目錄 {OriginalPath} 失敗，保留暫存目錄供人工檢視: {Path}", targetOriginal, entry.FullPath);
            }
        }
    }

    /// <summary>刪除對應 tombstone 目錄已不存在的 journal（搬移失敗或清理中斷所遺留）</summary>
    private static void CleanOrphanJournal(string root, FileSystemEntry entry, string fileName, HashSet<string> tombstoneNames)
    {
        if (!fileName.StartsWith(DeletePrefix, StringComparison.OrdinalIgnoreCase) ||
            !fileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase) ||
            tombstoneNames.Contains(Path.GetFileNameWithoutExtension(fileName)))
        {
            return;
        }

        if (SafeFileSystem.DeleteWithin(root, entry.FullPath))
        {
            Logger.Information("已清理孤兒刪除紀錄: {Path}", entry.FullPath);
        }
        else
        {
            Logger.Warning("清理孤兒刪除紀錄失敗: {Path}", entry.FullPath);
        }
    }

    /// <summary>安全清理指定 tombstone 目錄與其 journal 檔案</summary>
    public static bool CleanTombstone(string serversRoot, string tombstonePath, string? journalPath = null)
    {
        string root = SafeFileSystem.ResolveStableDirectory(serversRoot);
        bool success = SafeFileSystem.DeleteWithin(root, tombstonePath);

        if (!string.IsNullOrEmpty(journalPath))
        {
            SafeFileSystem.DeleteWithin(root, journalPath);
        }

        return success;
    }

    private static bool IsMatchingPrefix(string dirName, string[] prefixes)
    {
        foreach (string prefix in prefixes)
        {
            if (dirName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }
}
