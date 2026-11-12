using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器玩家設定與快取檔案儲存實作，支援 SafeFileSystem 與不可分割安全寫入</summary>
public sealed class ServerPlayerConfigStore : IServerPlayerConfigStore
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPlayerConfigStore));
    private const string OpsFileName = ServerDefaults.OpsFileName;
    private const string WhitelistFileName = ServerDefaults.WhitelistFileName;
    private const string BannedPlayersFileName = ServerDefaults.BannedPlayersFileName;
    private const string BannedIpsFileName = ServerDefaults.BannedIpsFileName;
    private const string UserCacheFileName = ServerDefaults.UserCacheFileName;

    /// <summary>讀取伺服器的名單設定（管理員、白名單、封鎖玩家與封鎖 IP 等）</summary>
    public async Task<ServerPlayerConfigBundle> LoadBundleAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        cancellationToken.ThrowIfCancellationRequested();

        return await Task.Run(() =>
        {
            var userCache = ReadJsonFile<ServerUserCacheEntry>(serverPath, UserCacheFileName);
            var ops = ReadJsonFile<ServerOperatorEntry>(serverPath, OpsFileName);
            var whitelist = ReadJsonFile<ServerWhitelistEntry>(serverPath, WhitelistFileName);
            var bannedPlayers = ReadJsonFile<ServerBannedPlayerEntry>(serverPath, BannedPlayersFileName);
            var bannedIps = ReadJsonFile<ServerBannedIpEntry>(serverPath, BannedIpsFileName);

            return new ServerPlayerConfigBundle(
                UserCache: userCache ?? [],
                Operators: ops ?? [],
                Whitelist: whitelist ?? [],
                BannedPlayers: bannedPlayers ?? [],
                BannedIps: bannedIps ?? []);
        }, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>將名單設定寫回伺服器資料夾</summary>
    public async Task SaveBundleAsync(string serverPath, ServerPlayerConfigBundle bundle, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        ArgumentNullException.ThrowIfNull(bundle);
        cancellationToken.ThrowIfCancellationRequested();

        await Task.Run(() =>
        {
            WriteJsonFile(serverPath, OpsFileName, bundle.Operators);
            WriteJsonFile(serverPath, WhitelistFileName, bundle.Whitelist);
            WriteJsonFile(serverPath, BannedPlayersFileName, bundle.BannedPlayers);
            WriteJsonFile(serverPath, BannedIpsFileName, bundle.BannedIps);
        }, cancellationToken).ConfigureAwait(false);
    }

    private static List<T>? ReadJsonFile<T>(string serverPath, string fileName)
    {
        try
        {
            string targetPath = Path.Combine(serverPath, fileName);
            if (!SafeFileSystem.FileExists(targetPath))
            {
                return null;
            }

            byte[]? bytes = SafeFileSystem.ReadRegularFile(targetPath, JsonCodec.DefaultMaxBytes);
            if (bytes is null || bytes.Length == 0)
            {
                return null;
            }

            return JsonCodec.Deserialize<List<T>>(bytes);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取伺服器玩家設定檔失敗: {FileName}", fileName);
            return null;
        }
    }

    private static void WriteJsonFile<T>(string serverPath, string fileName, IReadOnlyList<T> items)
    {
        string targetPath = Path.Combine(serverPath, fileName);
        var list = items is List<T> concreteList ? concreteList : [.. items];
        byte[]? bytes = JsonCodec.SerializeToUtf8Bytes(list, indented: true);
        if (bytes is null || !AtomicFileWriter.WriteBytes(targetPath, bytes))
        {
            throw new IOException($"無法以不可分割方式寫入伺服器玩家設定檔：{fileName}");
        }
    }
}
