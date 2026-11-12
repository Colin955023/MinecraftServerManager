using System.Diagnostics;
using System.Collections.Concurrent;
using System.Collections.Frozen;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerDirectorySizeService(
    TimeSpan cacheDuration,
    int maxEntries = SafeFileSystem.DefaultMaxEntries,
    long maxTotalBytes = SafeFileSystem.DefaultMaxTotalBytes) : IServerDirectorySizeService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerDirectorySizeService));

    private static readonly string[] ExcludedDirectoryNamesSource =
    [
        "backups"
    ];

    private static readonly FrozenSet<string> ExcludedDirectoryNames =
        ExcludedDirectoryNamesSource.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    private readonly TimeSpan _cacheDuration = cacheDuration;
    private readonly int _maxEntries = maxEntries;
    private readonly long _maxTotalBytes = maxTotalBytes;
    private readonly ConcurrentDictionary<string, (long SizeBytes, long ExpireTimestamp)> _cache =
        new(StringComparer.OrdinalIgnoreCase);

    public async Task<long> CalculateServerSizeAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return 0;
        }

        string normalizedPath = Path.GetFullPath(serverPath);
        long now = Stopwatch.GetTimestamp();

        if (_cache.TryGetValue(normalizedPath, out var cached) && cached.ExpireTimestamp > now)
        {
            return cached.SizeBytes;
        }

        long calculatedSize = await Task.Run(() =>
        {
            cancellationToken.ThrowIfCancellationRequested();

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
                    pruneDirectory: static (fullPath, name) => ExcludedDirectoryNames.Contains(name));

                long totalBytes = 0;

                foreach (var entry in entries)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    if (entry.IsDirectory)
                    {
                        continue;
                    }
                    totalBytes += entry.Length;
                }

                return totalBytes;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "計算伺服器容量失敗 ({Path})", normalizedPath);
                return -1L;
            }
        }, cancellationToken).ConfigureAwait(false);

        if (calculatedSize >= 0)
        {
            _cache[normalizedPath] = (calculatedSize, now + (long)(_cacheDuration.TotalSeconds * Stopwatch.Frequency));
        }

        return calculatedSize;
    }

    public string FormatServerSize(long bytes)
    {
        if (bytes < 0)
        {
            return "無法計算";
        }

        return bytes == 0 ? "-" : UnitFormatter.FormatBytes(bytes);
    }
}
