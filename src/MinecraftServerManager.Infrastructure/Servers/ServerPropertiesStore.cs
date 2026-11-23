using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerPropertiesStore : IServerPropertiesStore
{
    private const int MaxPropertiesFileBytes = 1024 * 1024; // 1 MB
    private const string MissingRevision = "missing";

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesStore));

    private readonly string _serversRoot;
    private readonly KeyedAsyncLock _writeGates = new();

    public ServerPropertiesStore(string serversRoot)
    {
        _serversRoot = serversRoot ?? string.Empty;
    }

    private string GetPropertiesFilePath(string serverName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        if (string.IsNullOrWhiteSpace(_serversRoot))
        {
            throw new InvalidOperationException("伺服器根目錄尚未設定");
        }
        string stableRoot = SafeFileSystem.ResolveStableDirectory(_serversRoot);
        string serverDir = ServerSetupHelpers.ResolveServerDirectory(stableRoot, serverName);
        return SafeFileSystem.ResolveStablePath(Path.Combine(serverDir, ServerDefaults.ServerPropertiesFileName));
    }

    public async Task<ServerPropertiesSnapshot> ReadAsync(
        string serverName,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            string path = GetPropertiesFilePath(serverName);
            if (!SafeFileSystem.FileExists(path))
            {
                return new ServerPropertiesSnapshot(
                    ServerName: serverName,
                    Status: ServerPropertiesReadStatus.Missing,
                    Revision: MissingRevision,
                    Properties: ServerPropertiesMetadata.DefaultProperties,
                    Message: "找不到 server.properties，已套用預設值");
            }

            // 單一串流內判斷大小並讀取，避免檢查與讀取之間檔案被改寫
            byte[] bytes;
            var stream = SafeFileSystem.OpenRead(path, FileShare.ReadWrite, FileOptions.Asynchronous | FileOptions.SequentialScan);
            await using (stream.ConfigureAwait(false))
            {
                if (stream.Length > MaxPropertiesFileBytes)
                {
                    return TooLarge(serverName);
                }

                // 多讀 1 位元組以偵測讀取期間檔案成長
                bytes = new byte[(int)stream.Length + 1];
                int totalRead = await stream.ReadAtLeastAsync(bytes, bytes.Length, throwOnEndOfStream: false, cancellationToken).ConfigureAwait(false);
                if (totalRead > MaxPropertiesFileBytes)
                {
                    return TooLarge(serverName);
                }

                bytes = bytes[..totalRead];
            }

            if (bytes.Length == 0)
            {
                return new ServerPropertiesSnapshot(
                    ServerName: serverName,
                    Status: ServerPropertiesReadStatus.Empty,
                    Revision: HashCalculator.DigestBytes([]),
                    Properties: ServerPropertiesMetadata.DefaultProperties,
                    Message: "server.properties 為空檔案，已套用預設值");
            }

            string revision = HashCalculator.DigestBytes(bytes);
            // 略過 UTF-8 BOM，避免第一個鍵帶有 \uFEFF
            string text = SafeFileSystem.DecodeUtf8WithoutBom(bytes);
            var properties = PropertiesDocumentCodec.Parse(text);

            return new ServerPropertiesSnapshot(
                ServerName: serverName,
                Status: ServerPropertiesReadStatus.Ok,
                Revision: revision,
                Properties: properties);
        }
        catch (Exception ex) when (ex is SafeFileSystemException or ArgumentException)
        {
            Logger.Warning(ex, "server.properties 路徑無效: {Server}", serverName);
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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取 server.properties 失敗: {Server}", serverName);
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

        // 同伺服器的讀取-比對-寫入須序列化，避免兩次更新以相同版本互相覆蓋
        using var gate = await _writeGates.AcquireAsync(serverName, cancellationToken).ConfigureAwait(false);
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
                Message: "伺服器屬性已被其他程式修改，版本發生衝突");
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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "寫入 server.properties 失敗: {Server}", serverName);
            return new ServerPropertiesUpdateResult(
                Success: false,
                Snapshot: current,
                ErrorKind: ServerPropertiesUpdateError.WriteFailed,
                Message: ex.Message);
        }
    }

    private static ServerPropertiesSnapshot TooLarge(string serverName) => new(
        ServerName: serverName,
        Status: ServerPropertiesReadStatus.Unreadable,
        Revision: string.Empty,
        Properties: new Dictionary<string, string>(),
        Message: "server.properties 檔案過大超過安全上限");

    private static string? ValidatePatches(IReadOnlyDictionary<string, string> patches)
    {
        foreach (var (key, value) in patches)
        {
            string defaultVal = ServerPropertiesMetadata.GetDefault(key, string.Empty);
            var (isValid, error) = ServerPropertiesValidator.ValidateProperty(key, value, defaultVal);
            if (!isValid)
            {
                return error;
            }
        }

        return null;
    }
}
