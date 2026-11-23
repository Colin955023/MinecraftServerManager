using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組快取索引持久化管理員</summary>
public sealed class ModIndexPersistence
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModIndexPersistence));
    private readonly string _indexFilePath;
    private readonly Lock _lock = new();
    private Dictionary<string, ModCacheEntry> _index = new(StringComparer.OrdinalIgnoreCase);
    private bool _dirty;

    /// <summary>索引檔存放於 <paramref name="modsDirectory"/> 下的 <c>.modcache</c></summary>
    public ModIndexPersistence(string modsDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        string cacheDir = Path.Combine(stableModsDir, ".modcache");
        SafeFileSystem.ResolveStableDirectory(cacheDir, create: true);

        try
        {
            SafeFileSystem.SetDirectoryHidden(cacheDir, hidden: true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "設定快取目錄隱藏屬性失敗");
        }

        _indexFilePath = Path.Combine(cacheDir, "mod_index.json");
        LoadIndex();
    }

    public IReadOnlyDictionary<string, string>? GetCachedMetadata(string fileName, long fileSizeBytes, long lastWriteTimeUtcTicks)
    {
        lock (_lock)
        {
            return _index.TryGetValue(fileName, out var entry)
                && entry.FileSizeBytes == fileSizeBytes
                && entry.LastWriteTimeUtcTicks == lastWriteTimeUtcTicks
                    ? entry.Metadata
                    : null;
        }
    }

    public void CacheMetadata(string fileName, IReadOnlyDictionary<string, string> metadata, long fileSizeBytes, long lastWriteTimeUtcTicks)
    {
        lock (_lock)
        {
            if (!_index.TryGetValue(fileName, out var entry))
            {
                entry = new ModCacheEntry();
                _index[fileName] = entry;
            }
            else if (entry.FileSizeBytes != fileSizeBytes || entry.LastWriteTimeUtcTicks != lastWriteTimeUtcTicks)
            {
                // 檔案已變更（含變為 0 位元組）：舊雜湊失效
                entry.Hashes = null;
            }

            entry.Metadata = metadata is Dictionary<string, string> dict && dict.Comparer == StringComparer.OrdinalIgnoreCase
                ? dict
                : new Dictionary<string, string>(metadata, StringComparer.OrdinalIgnoreCase);
            entry.FileSizeBytes = fileSizeBytes;
            entry.LastWriteTimeUtcTicks = lastWriteTimeUtcTicks;
            _dirty = true;
        }
    }

    public string? GetCachedHash(string fileName, string algorithm)
    {
        lock (_lock)
        {
            if (_index.TryGetValue(fileName, out var entry) && entry.Hashes is not null)
            {
                return entry.Hashes.TryGetValue(algorithm, out string? hash) ? hash : null;
            }
            return null;
        }
    }

    public void CacheHash(string fileName, string algorithm, string hash)
    {
        lock (_lock)
        {
            if (!_index.TryGetValue(fileName, out var entry))
            {
                entry = new ModCacheEntry();
                _index[fileName] = entry;
            }
            entry.Hashes ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            entry.Hashes[algorithm] = hash;
            _dirty = true;
        }
    }

    public void CleanupStaleEntries(IEnumerable<string> existingFileNames)
    {
        var existingSet = new HashSet<string>(existingFileNames, StringComparer.OrdinalIgnoreCase);
        lock (_lock)
        {
            var keysToRemove = _index.Keys.Where(k => !existingSet.Contains(k)).ToList();
            if (keysToRemove.Count > 0)
            {
                foreach (string? k in keysToRemove)
                {
                    _index.Remove(k);
                }
                _dirty = true;
            }
        }
    }

    public void Flush()
    {
        lock (_lock)
        {
            if (!_dirty)
            {
                return;
            }

            try
            {
                byte[]? utf8Bytes = JsonCodec.SerializeToUtf8Bytes(_index, indented: false);
                if (utf8Bytes is null)
                {
                    return;
                }
                // 寫入失敗時保留 dirty 旗標，下次 Flush 會重試
                _dirty = !AtomicFileWriter.WriteBytes(_indexFilePath, utf8Bytes);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "寫入模組索引檔案失敗: {IndexFilePath}", _indexFilePath);
            }
        }
    }

    private void LoadIndex()
    {
        lock (_lock)
        {
            var loaded = JsonCodec.TryReadOrPreserveCorrupt<Dictionary<string, ModCacheEntry>>(_indexFilePath);
            _index = loaded is not null
                ? new Dictionary<string, ModCacheEntry>(loaded, StringComparer.OrdinalIgnoreCase)
                : new Dictionary<string, ModCacheEntry>(StringComparer.OrdinalIgnoreCase);
        }
    }
}

internal sealed class ModCacheEntry
{
    public Dictionary<string, string>? Metadata { get; set; }
    public Dictionary<string, string>? Hashes { get; set; }
    public long FileSizeBytes { get; set; }
    public long LastWriteTimeUtcTicks { get; set; }
}
