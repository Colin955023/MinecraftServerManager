using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerDirectorySizeService : IServerDirectorySizeService
{
    // 僅排除伺服器根層的備份資料夾，子目錄（如模組資料）的同名資料夾仍計入
    private const string RootBackupsDirectoryName = ServerDefaults.BackupsDirectoryName;
    private const int MaxCacheEntries = 256;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerDirectorySizeService));

    private readonly TimeSpan _cacheDuration;
    private readonly int _maxEntries;
    private readonly long _maxTotalBytes;
    private readonly Lock _cacheLock = new();
    private readonly Dictionary<string, (long SizeBytes, long ExpireTimestamp)> _cache =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly TimeProvider _timeProvider;
    private readonly SingleFlight<string, long> _inFlight = new(StringComparer.OrdinalIgnoreCase);

    public ServerDirectorySizeService(
        TimeSpan cacheDuration,
        TimeProvider timeProvider,
        int maxEntries = SafeFileSystem.DefaultMaxEntries,
        long maxTotalBytes = SafeFileSystem.DefaultMaxTotalBytes)
    {
        ArgumentNullException.ThrowIfNull(timeProvider);
        _cacheDuration = cacheDuration;
        _timeProvider = timeProvider;
        _maxEntries = maxEntries;
        _maxTotalBytes = maxTotalBytes;
    }

    public async Task<long> CalculateServerSizeAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return 0;
        }

        cancellationToken.ThrowIfCancellationRequested();
        string normalizedPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(serverPath));
        lock (_cacheLock)
        {
            if (_cache.TryGetValue(normalizedPath, out var cached))
            {
                if (cached.ExpireTimestamp > _timeProvider.GetTimestamp())
                {
                    return cached.SizeBytes;
                }

                _cache.Remove(normalizedPath);
            }
        }

        // 同路徑並發請求共用同一次計算；個別呼叫端取消只停止等待
        return await _inFlight.WaitAsync(normalizedPath, CalculateAndCacheAsync, cancellationToken).ConfigureAwait(false);
    }

    private async Task<long> CalculateAndCacheAsync(string normalizedPath)
    {
        long calculatedSize = await Task.Run(() => CalculateSize(normalizedPath)).ConfigureAwait(false);
        if (calculatedSize >= 0)
        {
            // 到期時間自計算完成起算，避免大型目錄計算耗時吃掉快取效期
            long now = _timeProvider.GetTimestamp();
            long expiresAt = now + (long)(_cacheDuration.TotalSeconds * _timeProvider.TimestampFrequency);
            lock (_cacheLock)
            {
                foreach (string expiredPath in _cache
                    .Where(pair => pair.Value.ExpireTimestamp <= now)
                    .Select(static pair => pair.Key)
                    .ToArray())
                {
                    _cache.Remove(expiredPath);
                }

                if (!_cache.ContainsKey(normalizedPath) && _cache.Count >= MaxCacheEntries)
                {
                    string oldestPath = _cache.MinBy(static pair => pair.Value.ExpireTimestamp).Key;
                    _cache.Remove(oldestPath);
                }

                _cache[normalizedPath] = (calculatedSize, expiresAt);
            }
        }

        return calculatedSize;
    }

    private long CalculateSize(string normalizedPath)
    {
        if (!SafeFileSystem.DirectoryExists(normalizedPath))
        {
            return 0L;
        }

        try
        {
            var entries = SafeFileSystem.EnumerateBoundedTree(
                normalizedPath,
                maxEntries: _maxEntries,
                maxTotalBytes: _maxTotalBytes,
                rejectReparse: false,
                pruneDirectory: (fullPath, name) =>
                    string.Equals(name, RootBackupsDirectoryName, StringComparison.OrdinalIgnoreCase)
                    && string.Equals(Path.GetDirectoryName(fullPath), normalizedPath, StringComparison.OrdinalIgnoreCase));

            long totalBytes = 0;
            foreach (var entry in entries)
            {
                if (!entry.IsDirectory)
                {
                    totalBytes += entry.Length;
                }
            }

            return totalBytes;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "計算伺服器容量失敗 ({Path})", normalizedPath);
            return -1L;
        }
    }
}
