using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

/// <summary>
/// 伺服器刪除交易暫存目錄（Tombstone）記錄
/// </summary>
public sealed record DeleteTombstoneRecord(
    string ServerName,
    string OriginalPath,
    DateTime Timestamp,
    int SchemaVersion = 1);

/// <summary>
/// 伺服器刪除交易暫存與崩潰復原管理工具
/// </summary>
public static class ServerTombstoneManager
{
    public const string DeletePrefix = ".msm-delete-";
    public const string DeleteMarker = ".msm-delete-marker.json";

    /// <summary>
    /// 準備伺服器刪除 tombstone 並將目錄安全移入暫存
    /// </summary>
    public static (string TombstonePath, string JournalPath) PrepareDeleteTombstone(
        string serversRoot,
        string serverName,
        string originalPath)
    {
        string root = SafeFileSystem.ResolveStableDirectory(serversRoot);
        string original = Path.GetFullPath(originalPath);

        if (!Directory.Exists(original))
        {
            throw new DirectoryNotFoundException($"找不到伺服器目錄： {original}");
        }

        string validatedName = ServerName.Parse(serverName).Value;
        string tombstoneId = Guid.NewGuid().ToString("N");
        string tombstoneName = $"{DeletePrefix}{tombstoneId}";
        string tombstonePath = Path.Combine(root, tombstoneName);
        string journalPath = Path.Combine(root, $"{tombstoneName}.json");

        var record = new DeleteTombstoneRecord(validatedName, original, DateTime.UtcNow);
        string json = JsonCodec.Serialize(record);

        // 寫入外部日誌
        AtomicFileWriter.WriteText(journalPath, json);

        // 嚴格在邊界內移動目錄至 tombstone
        SafeFileSystem.MoveWithinStrict(root, original, tombstonePath);

        // 寫入內部標記
        string internalMarker = Path.Combine(tombstonePath, DeleteMarker);
        AtomicFileWriter.WriteText(internalMarker, json);

        return (tombstonePath, journalPath);
    }

    /// <summary>
    /// 於啟動時掃描並復原或清理未完成的刪除 tombstone
    /// </summary>
    public static void RecoverDeleteTombstones(
        string serversRoot,
        Func<string, string?> registeredServerLookup,
        Action<string>? onRecovered = null,
        Action<string>? onCleaned = null)
    {
        if (!Directory.Exists(serversRoot))
        {
            return;
        }

        string root = SafeFileSystem.ResolveStableDirectory(serversRoot);
        var entries = SafeFileSystem.ListBoundedDirectory(root, rejectReparse: false);

        foreach (var entry in entries)
        {
            string dirName = Path.GetFileName(entry.FullPath);
            if (!entry.IsDirectory || !dirName.StartsWith(DeletePrefix, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (SafeFileSystem.IsReparsePoint(entry.FullPath))
            {
                continue;
            }

            string markerPath = Path.Combine(entry.FullPath, DeleteMarker);
            string journalPath = Path.Combine(root, $"{dirName}.json");

            DeleteTombstoneRecord? record = null;
            if (File.Exists(markerPath))
            {
                try
                {
                    record = JsonCodec.Deserialize<DeleteTombstoneRecord>(File.ReadAllText(markerPath));
                }
                catch
                {
                    record = null;
                }
            }

            if (record == null && File.Exists(journalPath))
            {
                try
                {
                    record = JsonCodec.Deserialize<DeleteTombstoneRecord>(File.ReadAllText(journalPath));
                }
                catch
                {
                    record = null;
                }
            }

            if (record == null || record.SchemaVersion != 1 || string.IsNullOrWhiteSpace(record.ServerName))
            {
                // 無法驗證的項目保留以避免誤刪
                continue;
            }

            string? registeredPath = registeredServerLookup(record.ServerName);
            if (string.IsNullOrEmpty(registeredPath))
            {
                // 已從登錄中移除，確認已提交刪除，執行安全清理
                SafeFileSystem.DeleteWithin(root, entry.FullPath);
                SafeFileSystem.DeleteWithin(root, journalPath);
                onCleaned?.Invoke(record.ServerName);
                continue;
            }

            // 伺服器仍在登錄中，說明在 commit 前崩潰，進行 fail-safe 還原
            string targetOriginal = Path.GetFullPath(registeredPath);
            if (Directory.Exists(targetOriginal))
            {
                // 原目錄已存在，保留暫存目錄以避免覆蓋
                continue;
            }

            try
            {
                SafeFileSystem.MoveWithinStrict(root, entry.FullPath, targetOriginal);
                SafeFileSystem.DeleteWithin(targetOriginal, Path.Combine(targetOriginal, DeleteMarker));
                SafeFileSystem.DeleteWithin(root, journalPath);
                onRecovered?.Invoke(record.ServerName);
            }
            catch
            {
                // 若還原失敗則保留目錄供管理員檢視
            }
        }
    }

    /// <summary>
    /// 安全清理指定 tombstone 目錄與其 journal 檔案
    /// </summary>
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
}
