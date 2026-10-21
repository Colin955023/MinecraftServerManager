using System.Text.Encodings.Web;
using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Serialization;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器玩家設定與快取檔案儲存實作，支援 SafeFileSystem 與不可分割安全寫入
/// </summary>
public sealed class ServerPlayerConfigStore : IServerPlayerConfigStore
{
    private const string OpsFileName = "ops.json";
    private const string WhitelistFileName = "whitelist.json";
    private const string BannedPlayersFileName = "banned-players.json";
    private const string BannedIpsFileName = "banned-ips.json";
    private const string UserCacheFileName = "usercache.json";

    private static readonly JsonSerializerOptions IndentedJsonOptions = new()
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        TypeInfoResolver = AppJsonSerializerContext.Default,
    };

    /// <inheritdoc />
    public async Task<ServerPlayerConfigBundle> LoadBundleAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        cancellationToken.ThrowIfCancellationRequested();

        return await Task.Run(() =>
        {
            var userCache = ReadJsonFile(serverPath, UserCacheFileName, AppJsonSerializerContext.Default.ListServerUserCacheEntry);
            var ops = ReadJsonFile(serverPath, OpsFileName, AppJsonSerializerContext.Default.ListServerOperatorEntry);
            var whitelist = ReadJsonFile(serverPath, WhitelistFileName, AppJsonSerializerContext.Default.ListServerWhitelistEntry);
            var bannedPlayers = ReadJsonFile(serverPath, BannedPlayersFileName, AppJsonSerializerContext.Default.ListServerBannedPlayerEntry);
            var bannedIps = ReadJsonFile(serverPath, BannedIpsFileName, AppJsonSerializerContext.Default.ListServerBannedIpEntry);

            return new ServerPlayerConfigBundle(
                UserCache: userCache ?? [],
                Operators: ops ?? [],
                Whitelist: whitelist ?? [],
                BannedPlayers: bannedPlayers ?? [],
                BannedIps: bannedIps ?? []);
        }, cancellationToken).ConfigureAwait(false);
    }

    /// <inheritdoc />
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

    private static List<T>? ReadJsonFile<T>(string serverPath, string fileName, System.Text.Json.Serialization.Metadata.JsonTypeInfo<List<T>> typeInfo)
    {
        try
        {
            string targetPath = Path.Combine(serverPath, fileName);
            if (!File.Exists(targetPath))
            {
                return null;
            }

            byte[]? bytes = SafeFileSystem.ReadRegularFile(targetPath, JsonCodec.DefaultMaxBytes);
            if (bytes is null || bytes.Length == 0)
            {
                return null;
            }

            return JsonSerializer.Deserialize(bytes, typeInfo);
        }
        catch
        {
            return null;
        }
    }

    private static void WriteJsonFile<T>(string serverPath, string fileName, IReadOnlyList<T> items)
    {
        string targetPath = Path.Combine(serverPath, fileName);
        var list = items is List<T> concreteList ? concreteList : [.. items];
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(list, IndentedJsonOptions);
        if (!AtomicFileWriter.WriteBytes(targetPath, bytes))
        {
            throw new IOException($"無法以不可分割方式寫入伺服器玩家設定檔：{fileName}");
        }
    }
}
