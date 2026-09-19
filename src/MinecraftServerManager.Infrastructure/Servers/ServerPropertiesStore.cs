using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerPropertiesStore : IServerPropertiesStore
{
    private const int MaxPropertiesFileBytes = 1024 * 1024; // 1 MB
    private const string MissingRevision = "missing";
    private readonly string _serversRoot;

    public ServerPropertiesStore(string serversRoot)
    {
        _serversRoot = serversRoot ?? string.Empty;
    }

    public string GetPropertiesFilePath(string serverName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        if (string.IsNullOrWhiteSpace(_serversRoot))
        {
            throw new InvalidOperationException("伺服器根目錄尚未設定");
        }
        string stableRoot = SafeFileSystem.ResolveStableDirectory(_serversRoot);
        string serverDir = Path.Combine(stableRoot, serverName);
        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDir);
        string propertiesPath = Path.Combine(stableDir, "server.properties");
        return SafeFileSystem.ResolveStablePath(propertiesPath);
    }

    public async Task<ServerPropertiesSnapshot> ReadAsync(
        string serverName,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            string path = GetPropertiesFilePath(serverName);
            if (!File.Exists(path))
            {
                return new ServerPropertiesSnapshot(
                    ServerName: serverName,
                    Status: ServerPropertiesReadStatus.Missing,
                    Revision: MissingRevision,
                    Properties: ServerPropertiesMetadata.DefaultProperties,
                    Message: "找不到 server.properties，已套用預設值");
            }

            var fileInfo = new FileInfo(path);
            if (fileInfo.Length == 0)
            {
                string emptyHash = HashCalculator.DigestBytes(ReadOnlySpan<byte>.Empty);
                return new ServerPropertiesSnapshot(
                    ServerName: serverName,
                    Status: ServerPropertiesReadStatus.Empty,
                    Revision: emptyHash,
                    Properties: ServerPropertiesMetadata.DefaultProperties,
                    Message: "server.properties 為空檔案，已套用預設值");
            }

            if (fileInfo.Length > MaxPropertiesFileBytes)
            {
                return new ServerPropertiesSnapshot(
                    ServerName: serverName,
                    Status: ServerPropertiesReadStatus.Unreadable,
                    Revision: string.Empty,
                    Properties: new Dictionary<string, string>(),
                    Message: "server.properties 檔案過大超過安全上限");
            }

            byte[] bytes = await File.ReadAllBytesAsync(path, cancellationToken).ConfigureAwait(false);
            string revision = HashCalculator.DigestBytes(bytes);
            string text = Encoding.UTF8.GetString(bytes);
            var properties = PropertiesDocumentCodec.Parse(text);

            return new ServerPropertiesSnapshot(
                ServerName: serverName,
                Status: ServerPropertiesReadStatus.Ok,
                Revision: revision,
                Properties: properties);
        }
        catch (SafeFileSystemException ex)
        {
            return new ServerPropertiesSnapshot(
                ServerName: serverName,
                Status: ServerPropertiesReadStatus.Invalid,
                Revision: string.Empty,
                Properties: new Dictionary<string, string>(),
                Message: ex.Message);
        }
        catch (DirectoryNotFoundException)
        {
            return new ServerPropertiesSnapshot(
                ServerName: serverName,
                Status: ServerPropertiesReadStatus.Missing,
                Revision: MissingRevision,
                Properties: new Dictionary<string, string>(),
                Message: "找不到伺服器目錄");
        }
        catch (Exception ex)
        {
            return new ServerPropertiesSnapshot(
                ServerName: serverName,
                Status: ServerPropertiesReadStatus.Unreadable,
                Revision: string.Empty,
                Properties: new Dictionary<string, string>(),
                Message: ex.Message);
        }
    }

    public async Task<ServerPropertiesUpdateResult> UpdateAsync(
        string serverName,
        IReadOnlyDictionary<string, string> patches,
        string expectedRevision,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(patches);
        cancellationToken.ThrowIfCancellationRequested();

        var current = await ReadAsync(serverName, cancellationToken).ConfigureAwait(false);
        if (!current.Readable)
        {
            return new ServerPropertiesUpdateResult(
                Success: false,
                Snapshot: current,
                ErrorKind: ServerPropertiesUpdateError.ReadFailed,
                Message: current.Message);
        }

        if (!string.Equals(current.Revision, expectedRevision, StringComparison.OrdinalIgnoreCase))
        {
            return new ServerPropertiesUpdateResult(
                Success: false,
                Snapshot: current,
                ErrorKind: ServerPropertiesUpdateError.Conflict,
                Message: "伺服器屬性已被其他程序修改，版本發生衝突");
        }

        string? validationError = ValidatePatches(patches);
        if (validationError is not null)
        {
            return new ServerPropertiesUpdateResult(
                Success: false,
                Snapshot: current,
                ErrorKind: ServerPropertiesUpdateError.Invalid,
                Message: validationError);
        }

        var merged = new Dictionary<string, string>(current.Properties, StringComparer.OrdinalIgnoreCase);
        foreach (var (key, value) in patches)
        {
            merged[key] = value;
        }

        try
        {
            string path = GetPropertiesFilePath(serverName);
            string serialized = PropertiesDocumentCodec.Serialize(merged);
            if (!AtomicFileWriter.WriteText(path, serialized))
            {
                return new ServerPropertiesUpdateResult(
                    Success: false,
                    Snapshot: current,
                    ErrorKind: ServerPropertiesUpdateError.WriteFailed,
                    Message: "寫入 server.properties 失敗");
            }

            var updated = await ReadAsync(serverName, cancellationToken).ConfigureAwait(false);
            return new ServerPropertiesUpdateResult(
                Success: true,
                Snapshot: updated);
        }
        catch (Exception ex)
        {
            return new ServerPropertiesUpdateResult(
                Success: false,
                Snapshot: current,
                ErrorKind: ServerPropertiesUpdateError.WriteFailed,
                Message: ex.Message);
        }
    }

    public async Task<ServerPropertiesMigrationPlan> MigrateAsync(
        string serverName,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default)
    {
        var snapshot = await ReadAsync(serverName, cancellationToken).ConfigureAwait(false);
        if (!snapshot.Readable || snapshot.Properties.Count == 0)
        {
            return new ServerPropertiesMigrationPlan(false, [], snapshot.Properties);
        }

        var plan = ServerPropertiesMigrationService.PlanMigration(snapshot.Properties, minecraftVersion);
        if (plan.NeedsMigration)
        {
            string stableRoot = SafeFileSystem.ResolveStableDirectory(_serversRoot);
            string serverDir = Path.Combine(stableRoot, serverName);
            ServerPropertiesMigrationService.ApplyMigrationToDirectory(serverDir, plan, createBackup: true);
        }

        return plan;
    }

    private static string? ValidatePatches(IReadOnlyDictionary<string, string> patches)
    {
        foreach (var (key, value) in patches)
        {
            if (string.Equals(key, "server-port", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(key, "query.port", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(key, "rcon.port", StringComparison.OrdinalIgnoreCase))
            {
                if (!int.TryParse(value, out int port) || port is < 1 or > 65534)
                {
                    return $"連接埠 {key} 必須在 1 到 65534 之間";
                }
            }
            else if (string.Equals(key, "max-players", StringComparison.OrdinalIgnoreCase))
            {
                if (!int.TryParse(value, out int players) || players < 0)
                {
                    return "max-players 必須大於或等於 0";
                }
            }
            else if (string.Equals(key, "difficulty", StringComparison.OrdinalIgnoreCase))
            {
                string lower = value.Trim().ToLowerInvariant();
                if (lower is not ("peaceful" or "easy" or "normal" or "hard"))
                {
                    return $"難度設定值無效：{value}";
                }
            }
            else if (string.Equals(key, "gamemode", StringComparison.OrdinalIgnoreCase))
            {
                string lower = value.Trim().ToLowerInvariant();
                if (lower is not ("survival" or "creative" or "adventure" or "spectator"))
                {
                    return $"遊戲模式設定值無效：{value}";
                }
            }
        }

        return null;
    }
}
