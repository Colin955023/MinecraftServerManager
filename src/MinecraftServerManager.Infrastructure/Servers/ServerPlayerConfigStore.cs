using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerPlayerConfigStore : IServerPlayerConfigStore
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPlayerConfigStore));
    private const string OpsFileName = ServerDefaults.OpsFileName;
    private const string WhitelistFileName = ServerDefaults.WhitelistFileName;
    private const string BannedPlayersFileName = ServerDefaults.BannedPlayersFileName;
    private const string BannedIpsFileName = ServerDefaults.BannedIpsFileName;
    private const string UserCacheFileName = ServerDefaults.UserCacheFileName;

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

            var items = JsonCodec.Deserialize<List<T>>(bytes);
            if (items is null)
            {
                // 損毀內容另存 .bad，避免下次儲存以空清單覆蓋後無從復原
                Logger.Warning("伺服器玩家設定檔內容無法解析，已另存為 .bad: {FileName}", fileName);
                SafeFileSystem.TryPreserveCorruptFile(targetPath, Logger);
            }

            return items;
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
        AtomicFileWriter.WriteJsonOrThrow(targetPath, list, indented: true);
    }
}
