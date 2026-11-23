using System.Text.Json.Serialization;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器清單檔（servers.json）存取</summary>
internal sealed class ServerRegistryStore
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerRegistryStore));
    private readonly string _serversRoot;
    private readonly string _registryFilePath;
    private readonly Lock _lock = new();
    private Dictionary<string, ServerConfigPayload>? _cachedRegistry;
    private IReadOnlyList<ServerConfig>? _cachedParsedList;
    private Dictionary<string, ServerConfig>? _cachedParsedMap;
    private DateTime _lastRegistryWriteTimeUtc;
    private long _lastRegistryLength = -1;
    private bool _unreadableRegistryPreserved;
    private readonly HashSet<string> _reportedInvalidEntries = new(StringComparer.OrdinalIgnoreCase);

    private const int WriteReadRetryCount = 3;
    private static readonly TimeSpan WriteReadRetryDelay = TimeSpan.FromMilliseconds(100);

    public ServerRegistryStore(string serversRoot)
    {
        _serversRoot = serversRoot;
        _registryFilePath = Path.Combine(serversRoot, ServerDefaults.RegistryFileName);
    }

    /// <summary>取得所有可解析的伺服器設定（快取命中時直接回傳快照）</summary>
    public IReadOnlyList<ServerConfig> GetAll()
    {
        lock (_lock)
        {
            ReadRegistry();
            return _cachedParsedList ?? [];
        }
    }

    /// <summary>依名稱（不分大小寫）取得伺服器設定（快取命中時直接查詢已解析快照）</summary>
    public ServerConfig? Find(string name)
    {
        lock (_lock)
        {
            ReadRegistry();
            return _cachedParsedMap is not null && _cachedParsedMap.TryGetValue(name, out var config)
                ? config
                : null;
        }
    }

    /// <summary>取得伺服器清單檔記錄的實際路徑（供墓碑復原使用）</summary>
    public string? FindPath(string name)
    {
        lock (_lock)
        {
            return ReadRegistry().TryGetValue(name, out var cfg) ? cfg.Path : null;
        }
    }

    /// <summary>取得伺服器清單檔目前內容的複本（供掃描比對已註冊名稱與路徑）</summary>
    public IReadOnlyDictionary<string, ServerConfigPayload> Snapshot()
    {
        lock (_lock)
        {
            return LoadRegistry();
        }
    }

    public void Set(string key, ServerConfig config) =>
        Update(registry => registry[key] = ServerConfigPayload.FromDomain(config));

    public void Remove(string key) =>
        Update(registry => { registry.Remove(key); });

    /// <summary>鎖內載入、交給委派修改後儲存一次</summary>
    public void Update(Action<IDictionary<string, ServerConfigPayload>> mutate) =>
        Update<object?>(registry =>
        {
            mutate(registry);
            return null;
        });

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
            int memoryMax = payload.MemoryMaxMb > 0 ? payload.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb;
            config = new ServerConfig(
                name: name,
                minecraftVersion: mcVer,
                loaderType: loader,
                loaderVersion: payload.LoaderVersion ?? string.Empty,
                memoryMaxMb: memoryMax,
                memoryMinMb: payload.MemoryMinMb is > 0 and var min && min <= memoryMax ? min : null,
                path: payload.Path ?? Path.Combine(serversRoot, payload.Name),
                jvmArgs: payload.JvmArgs,
                backupPath: payload.BackupPath ?? string.Empty);
            return true;
        }

        config = null;
        return false;
    }

    /// <summary>鎖內取得可修改的伺服器清單檔複本；供寫入使用，讀取失敗時重試，仍無法取得原內容則擲出，絕不以空白清單覆寫</summary>
    private Dictionary<string, ServerConfigPayload> LoadRegistry() =>
        SafeFileSystem.RetryOnTransientIo(
            () => LoadRegistryOnce(),
            _registryFilePath,
            WriteReadRetryCount,
            WriteReadRetryDelay,
            static (ex, _) => ex is IOException or UnauthorizedAccessException);

    private Dictionary<string, ServerConfigPayload> LoadRegistryOnce()
    {
        if (TryReadRegistryCore() is { } registry)
        {
            return new Dictionary<string, ServerConfigPayload>(registry, StringComparer.OrdinalIgnoreCase);
        }

        // 內容損毀：原檔已另存 .bad 才允許以空白清單覆寫
        if (PreserveUnreadableRegistry())
        {
            return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
        }

        throw new InvalidDataException($"伺服器清單檔無法解析且無法備份，已停止寫入以免覆蓋：{_registryFilePath}");
    }

    /// <summary>鎖內取得伺服器清單檔內容；快取命中時直接回傳快取本體（不複製），呼叫端只能唯讀使用且不得外洩。讀取失敗時以空白清單呈現</summary>
    private Dictionary<string, ServerConfigPayload> ReadRegistry()
    {
        try
        {
            if (TryReadRegistryCore() is { } registry)
            {
                return registry;
            }

            // 內容無法解析（損毀或空白）：保留原檔後以空白清單呈現
            Logger.Warning("伺服器清單檔內容無法解析，使用空白清單: {Path}", _registryFilePath);
            PreserveUnreadableRegistry();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "讀取伺服器清單檔失敗，使用空白清單: {Path}", _registryFilePath);
        }

        return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>讀取並快取伺服器清單檔；檔案不存在回傳空清單，內容無法解析回傳 null，I/O 失敗擲出</summary>
    private Dictionary<string, ServerConfigPayload>? TryReadRegistryCore()
    {
        if (!SafeFileSystem.FileExists(_registryFilePath))
        {
            _cachedRegistry = new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
            _lastRegistryLength = -1;
            RebuildParsedCache(_cachedRegistry);
            return _cachedRegistry;
        }

        // 寫入時間精度不足時以檔案大小輔助判斷外部修改
        DateTime lastWrite = SafeFileSystem.GetFileLastWriteTimeUtc(_registryFilePath);
        long length = SafeFileSystem.GetFileLength(_registryFilePath);
        if (_cachedRegistry is not null && lastWrite == _lastRegistryWriteTimeUtc && length == _lastRegistryLength)
        {
            return _cachedRegistry;
        }

        var loaded = JsonCodec.ReadFile<Dictionary<string, ServerConfigPayload>>(_registryFilePath);
        if (loaded is null)
        {
            return null;
        }

        _cachedRegistry = new Dictionary<string, ServerConfigPayload>(loaded, StringComparer.OrdinalIgnoreCase);
        _lastRegistryWriteTimeUtc = lastWrite;
        _lastRegistryLength = length;
        RebuildParsedCache(_cachedRegistry);
        return _cachedRegistry;
    }

    private void RebuildParsedCache(Dictionary<string, ServerConfigPayload> registry)
    {
        var list = new List<ServerConfig>(registry.Count);
        var map = new Dictionary<string, ServerConfig>(registry.Count, StringComparer.OrdinalIgnoreCase);
        foreach (var (key, payload) in registry)
        {
            if (TryCreateServerConfig(payload, _serversRoot, out var config))
            {
                list.Add(config!);
                map[key] = config!;
            }
            else if (_reportedInvalidEntries.Add(key))
            {
                Logger.Warning("伺服器清單檔條目無效，已略過: {Key} (版本: {Version}, 載入器: {Loader})", key, payload.MinecraftVersion, payload.LoaderType);
            }
        }

        _cachedParsedList = list;
        _cachedParsedMap = map;
    }

    /// <summary>伺服器清單檔無法讀取時另存為 <c>.bad</c>；回傳原檔是否已妥善保存</summary>
    private bool PreserveUnreadableRegistry()
    {
        if (_unreadableRegistryPreserved)
        {
            return true;
        }

        if (SafeFileSystem.TryPreserveCorruptFile(_registryFilePath, Logger))
        {
            _unreadableRegistryPreserved = true;
            return true;
        }

        return false;
    }

    private void SaveRegistry(Dictionary<string, ServerConfigPayload> registry)
    {
        _unreadableRegistryPreserved = false;
        AtomicFileWriter.WriteJsonOrThrow(_registryFilePath, registry);
        _cachedRegistry = new Dictionary<string, ServerConfigPayload>(registry, StringComparer.OrdinalIgnoreCase);
        RebuildParsedCache(_cachedRegistry);
        if (SafeFileSystem.FileExists(_registryFilePath))
        {
            _lastRegistryWriteTimeUtc = SafeFileSystem.GetFileLastWriteTimeUtc(_registryFilePath);
            _lastRegistryLength = SafeFileSystem.GetFileLength(_registryFilePath);
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
