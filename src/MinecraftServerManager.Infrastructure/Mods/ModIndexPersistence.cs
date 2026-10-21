using System.Text.Json;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Serialization;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組快取索引持久化管理員
/// </summary>
public sealed class ModIndexPersistence : IModIndexPersistence
{
    private readonly string _indexFilePath;
    private readonly Lock _lock = new();
    private Dictionary<string, ModCacheEntry> _index = new(StringComparer.OrdinalIgnoreCase);
    private bool _dirty;

    public ModIndexPersistence(string serverDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string cacheDir = Path.Combine(stableServerDir, ".modcache");
        SafeFileSystem.ResolveStableDirectory(cacheDir, create: true);

        try
        {
            var dirInfo = new DirectoryInfo(cacheDir);
            if ((dirInfo.Attributes & FileAttributes.Hidden) == 0)
            {
                dirInfo.Attributes |= FileAttributes.Hidden;
            }
        }
        catch
        {
        }

        _indexFilePath = Path.Combine(cacheDir, "mod_index.json");
        LoadIndex();
    }

    internal ModCacheEntry? GetEntry(string fileName)
    {
        lock (_lock)
        {
            return _index.TryGetValue(fileName, out var entry) ? entry : null;
        }
    }

    public IReadOnlyDictionary<string, string>? GetCachedMetadata(string fileName)
    {
        lock (_lock)
        {
            return _index.TryGetValue(fileName, out var entry) ? entry.Metadata : null;
        }
    }

    public void CacheMetadata(string fileName, IReadOnlyDictionary<string, string> metadata) =>
        CacheMetadata(fileName, metadata, 0, 0);

    internal void CacheMetadata(string fileName, IReadOnlyDictionary<string, string> metadata, long fileSizeBytes, long lastWriteTimeUtcTicks)
    {
        lock (_lock)
        {
            if (!_index.TryGetValue(fileName, out var entry))
            {
                entry = new ModCacheEntry();
                _index[fileName] = entry;
            }
            else if ((fileSizeBytes > 0 || lastWriteTimeUtcTicks > 0) &&
                     (entry.FileSizeBytes != fileSizeBytes || entry.LastWriteTimeUtcTicks != lastWriteTimeUtcTicks))
            {
                entry.Hashes = null;
            }

            entry.Metadata = metadata is Dictionary<string, string> dict && dict.Comparer == StringComparer.OrdinalIgnoreCase
                ? dict
                : new Dictionary<string, string>(metadata, StringComparer.OrdinalIgnoreCase);
            if (fileSizeBytes > 0)
            {
                entry.FileSizeBytes = fileSizeBytes;
            }
            if (lastWriteTimeUtcTicks > 0)
            {
                entry.LastWriteTimeUtcTicks = lastWriteTimeUtcTicks;
            }
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

    public void MarkIssue(string fileName, string reason)
    {
        lock (_lock)
        {
            if (!_index.TryGetValue(fileName, out var entry))
            {
                entry = new ModCacheEntry();
                _index[fileName] = entry;
            }
            entry.Issue = reason;
            _dirty = true;
        }
    }

    public void ClearIndex()
    {
        lock (_lock)
        {
            _index.Clear();
            _dirty = true;
            Flush();
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
                byte[] utf8Bytes = JsonSerializer.SerializeToUtf8Bytes(_index, AppJsonSerializerContext.Default.DictionaryStringModCacheEntry);
                AtomicFileWriter.WriteBytes(_indexFilePath, utf8Bytes);
                _dirty = false;
            }
            catch
            {
            }
        }
    }

    private void LoadIndex()
    {
        lock (_lock)
        {
            if (!File.Exists(_indexFilePath))
            {
                _index = new Dictionary<string, ModCacheEntry>(StringComparer.OrdinalIgnoreCase);
                return;
            }

            try
            {
                byte[]? bytes = SafeFileSystem.ReadRegularFile(_indexFilePath, JsonCodec.DefaultMaxBytes);
                var loaded = bytes is not null
                    ? JsonSerializer.Deserialize(bytes, AppJsonSerializerContext.Default.DictionaryStringModCacheEntry)
                    : null;
                _index = loaded is not null
                    ? new Dictionary<string, ModCacheEntry>(loaded, StringComparer.OrdinalIgnoreCase)
                    : new Dictionary<string, ModCacheEntry>(StringComparer.OrdinalIgnoreCase);
            }
            catch
            {
                _index = new Dictionary<string, ModCacheEntry>(StringComparer.OrdinalIgnoreCase);
            }
        }
    }
}

internal sealed class ModCacheEntry
{
    public Dictionary<string, string>? Metadata { get; set; }
    public Dictionary<string, string>? Hashes { get; set; }
    public string? Issue { get; set; }
    public long FileSizeBytes { get; set; }
    public long LastWriteTimeUtcTicks { get; set; }
}
