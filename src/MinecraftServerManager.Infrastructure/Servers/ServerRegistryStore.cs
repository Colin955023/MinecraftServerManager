using System.Text.Json.Serialization;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器登錄檔（servers.json）存取：負責載入、快取、損毀保護與原子寫入，所有公開方法皆自行持鎖</summary>
internal sealed class ServerRegistryStore
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerRegistryStore));
    private readonly string _serversRoot;
    private readonly string _registryFilePath;
    private readonly Lock _lock = new();
    private Dictionary<string, ServerConfigPayload>? _cachedRegistry;
    private DateTime _lastRegistryWriteTimeUtc;
    private bool _unreadableRegistryPreserved;

    public ServerRegistryStore(string serversRoot)
    {
        _serversRoot = serversRoot;
        _registryFilePath = Path.Combine(serversRoot, ServerDefaults.RegistryFileName);
    }

    /// <summary>取得所有可解析的伺服器設定</summary>
    public IReadOnlyList<ServerConfig> GetAll()
    {
        lock (_lock)
        {
            var result = new List<ServerConfig>();
            foreach (var payload in LoadRegistry().Values)
            {
                if (TryCreateServerConfig(payload, _serversRoot, out var config))
                {
                    result.Add(config!);
                }
            }

            return result;
        }
    }

    /// <summary>依名稱（不分大小寫）取得伺服器設定</summary>
    public ServerConfig? Find(string name)
    {
        lock (_lock)
        {
            return LoadRegistry().TryGetValue(name, out var payload) && TryCreateServerConfig(payload, _serversRoot, out var config)
                ? config
                : null;
        }
    }

    /// <summary>取得登錄檔記錄的實際路徑（供墓碑復原使用）</summary>
    public string? FindPath(string name)
    {
        lock (_lock)
        {
            return LoadRegistry().TryGetValue(name, out var cfg) ? cfg.Path : null;
        }
    }

    /// <summary>取得登錄檔目前內容的複本（供掃描比對已註冊名稱與路徑）</summary>
    public IReadOnlyDictionary<string, ServerConfigPayload> Snapshot()
    {
        lock (_lock)
        {
            return LoadRegistry();
        }
    }

    /// <summary>以指定鍵新增或更新伺服器設定</summary>
    public void Set(string key, ServerConfig config)
    {
        lock (_lock)
        {
            var registry = LoadRegistry();
            registry[key] = ServerConfigPayload.FromDomain(config);
            SaveRegistry(registry);
        }
    }

    /// <summary>移除指定鍵的伺服器設定</summary>
    public void Remove(string key)
    {
        lock (_lock)
        {
            var registry = LoadRegistry();
            registry.Remove(key);
            SaveRegistry(registry);
        }
    }

    /// <summary>鎖內載入、交給委派修改後儲存一次並回傳結果</summary>
    public TResult Update<TResult>(Func<IDictionary<string, ServerConfigPayload>, TResult> mutate)
    {
        lock (_lock)
        {
            var registry = LoadRegistry();
            TResult result = mutate(registry);
            SaveRegistry(registry);
            return result;
        }
    }

    private static bool TryCreateServerConfig(ServerConfigPayload payload, string serversRoot, out ServerConfig? config)
    {
        if (ServerName.TryParse(payload.Name, out var name)
            && MinecraftVersion.TryParse(payload.MinecraftVersion, out var mcVer)
            && LoaderKinds.TryParse(payload.LoaderType, out var loader))
        {
            config = new ServerConfig(
                name: name,
                minecraftVersion: mcVer,
                loaderType: loader,
                loaderVersion: payload.LoaderVersion ?? string.Empty,
                memoryMaxMb: payload.MemoryMaxMb > 0 ? payload.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb,
                memoryMinMb: payload.MemoryMinMb,
                path: payload.Path ?? Path.Combine(serversRoot, payload.Name),
                jvmArgs: payload.JvmArgs,
                backupPath: payload.BackupPath ?? string.Empty);
            return true;
        }

        config = null;
        return false;
    }

    private Dictionary<string, ServerConfigPayload> LoadRegistry()
    {
        if (!SafeFileSystem.FileExists(_registryFilePath))
        {
            _cachedRegistry = new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
            return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
        }

        try
        {
            DateTime lastWrite = SafeFileSystem.GetFileLastWriteTimeUtc(_registryFilePath);
            if (_cachedRegistry is not null && lastWrite == _lastRegistryWriteTimeUtc)
            {
                return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
            }

            var loaded = JsonCodec.ReadFile<Dictionary<string, ServerConfigPayload>>(_registryFilePath);
            if (loaded is null)
            {
                // 內容無法解析（損毀或空白）：保留原檔後以空白清單繼續，避免下次儲存永久覆蓋
                Logger.Warning("伺服器登錄檔內容無法解析，使用空白清單: {Path}", _registryFilePath);
                PreserveUnreadableRegistry();
                return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
            }

            _cachedRegistry = new Dictionary<string, ServerConfigPayload>(loaded, StringComparer.OrdinalIgnoreCase);
            _lastRegistryWriteTimeUtc = lastWrite;
            return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "讀取伺服器登錄檔失敗，使用空白清單: {Path}", _registryFilePath);
            PreserveUnreadableRegistry();
            return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
        }
    }

    /// <summary>登錄檔無法讀取時保留原檔為 <c>.bad</c>，避免下次儲存以空白清單覆寫而永久遺失</summary>
    private void PreserveUnreadableRegistry()
    {
        if (_unreadableRegistryPreserved)
        {
            return;
        }

        try
        {
            SafeFileSystem.CopyFile(_registryFilePath, _registryFilePath + ".bad", overwrite: true);
            _unreadableRegistryPreserved = true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "無法備份損毀的伺服器登錄檔: {Path}", _registryFilePath);
        }
    }

    private void SaveRegistry(Dictionary<string, ServerConfigPayload> registry)
    {
        _unreadableRegistryPreserved = false;
        AtomicFileWriter.WriteJsonOrThrow(_registryFilePath, registry);
        _cachedRegistry = new Dictionary<string, ServerConfigPayload>(registry, StringComparer.OrdinalIgnoreCase);
        if (SafeFileSystem.FileExists(_registryFilePath))
        {
            _lastRegistryWriteTimeUtc = SafeFileSystem.GetFileLastWriteTimeUtc(_registryFilePath);
        }
    }
}

internal sealed record ServerConfigPayload(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("minecraftVersion")] string MinecraftVersion,
    [property: JsonPropertyName("loaderType")] string LoaderType,
    [property: JsonPropertyName("loaderVersion")] string LoaderVersion,
    [property: JsonPropertyName("memoryMaxMb")] int MemoryMaxMb,
    [property: JsonPropertyName("memoryMinMb")] int? MemoryMinMb,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("jvmArgs")] IReadOnlyList<string> JvmArgs,
    [property: JsonPropertyName("backupPath")] string BackupPath)
{
    public static ServerConfigPayload FromDomain(ServerConfig config) => new(
        Name: config.Name.Value,
        MinecraftVersion: config.MinecraftVersion.Value,
        LoaderType: config.LoaderType.ToString(),
        LoaderVersion: config.LoaderVersion,
        MemoryMaxMb: config.MemoryMaxMb,
        MemoryMinMb: config.MemoryMinMb,
        Path: config.Path,
        JvmArgs: config.JvmArgs,
        BackupPath: config.BackupPath);
}
