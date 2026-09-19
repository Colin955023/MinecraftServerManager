using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

/// <summary>
/// 伺服器還原交易中斷記錄
/// </summary>
public sealed record RestoreTransactionRecord(
    string ServerName,
    string OriginalPath,
    string PreparedPath,
    int SchemaVersion = 1);

/// <summary>
/// 伺服器還原中斷交易復原工具
/// </summary>
public static class RestoreTransactionRecovery
{
    private const string RestoreRollbackPrefix = ".restore-rollback-";

    /// <summary>
    /// 掃描並復原中斷的伺服器還原交易
    /// </summary>
    public static void RecoverRestoreTransactions(
        IEnumerable<(string ServerName, string ServerPath)> registeredServers,
        Action<string>? onRecovered = null)
    {
        foreach (var (serverName, serverPathStr) in registeredServers)
        {
            if (string.IsNullOrWhiteSpace(serverPathStr))
            {
                continue;
            }

            string serverPath = Path.GetFullPath(serverPathStr);
            string? parent = Path.GetDirectoryName(serverPath);
            if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent))
            {
                continue;
            }

            string stableParent;
            try
            {
                stableParent = SafeFileSystem.ResolveStableDirectory(parent);
            }
            catch
            {
                continue;
            }

            string serverDirName = Path.GetFileName(serverPath);
            string prefix = $".{serverDirName}{RestoreRollbackPrefix}";

            var entries = SafeFileSystem.ListBoundedDirectory(stableParent, rejectReparse: false);
            foreach (var entry in entries)
            {
                string name = Path.GetFileName(entry.FullPath);
                if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) || !name.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                RestoreTransactionRecord? payload = null;
                try
                {
                    payload = JsonCodec.Deserialize<RestoreTransactionRecord>(File.ReadAllText(entry.FullPath));
                }
                catch
                {
                    payload = null;
                }

                if (payload == null || payload.SchemaVersion != 1)
                {
                    continue;
                }

                string rollbackDirName = name[..^5]; // 去除 .json
                string rollbackPath = Path.Combine(stableParent, rollbackDirName);

                if (!Directory.Exists(rollbackPath) || SafeFileSystem.IsReparsePoint(rollbackPath))
                {
                    if (Directory.Exists(serverPath))
                    {
                        SafeFileSystem.DeleteWithin(stableParent, entry.FullPath);
                    }
                    continue;
                }

                try
                {
                    if (Directory.Exists(serverPath))
                    {
                        // 原目錄已存在，說明還原已成功完成或無需還原，清理暫存
                        SafeFileSystem.DeleteWithin(stableParent, rollbackPath);
                        SafeFileSystem.DeleteWithin(stableParent, entry.FullPath);
                        continue;
                    }

                    // 原目錄遺失，使用 rollback 暫存復原原始伺服器
                    if (SafeFileSystem.MoveWithin(stableParent, rollbackPath, serverPath))
                    {
                        SafeFileSystem.DeleteWithin(stableParent, entry.FullPath);
                        onRecovered?.Invoke(serverName);
                    }
                }
                catch
                {
                    // 發生例外時保留目錄供檢視
                }
            }
        }
    }
}
