using System.Collections.Concurrent;
using System.Collections.Frozen;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerDirectorySizeService : IServerDirectorySizeService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerDirectorySize");

    private static readonly string[] ExcludedDirectoryNamesSource =
    [
        "backups"
    ];

    private static readonly FrozenSet<string> ExcludedDirectoryNames =
        ExcludedDirectoryNamesSource.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    private static readonly TimeSpan DefaultCacheDuration = TimeSpan.FromSeconds(60);

    private readonly TimeSpan _cacheDuration;
    private readonly ConcurrentDictionary<string, (long SizeBytes, DateTime ExpireAt)> _cache =
        new(StringComparer.OrdinalIgnoreCase);

    public ServerDirectorySizeService(TimeSpan? cacheDuration = null)
    {
        _cacheDuration = cacheDuration ?? DefaultCacheDuration;
    }

    public async Task<long> CalculateServerSizeAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return 0;
        }

        string normalizedPath = Path.GetFullPath(serverPath);
        DateTime now = DateTime.UtcNow;

        if (_cache.TryGetValue(normalizedPath, out var cached) && cached.ExpireAt > now)
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
                var entries = SafeFileSystem.WalkBoundedTree(normalizedPath, rejectReparse: false);
                long totalBytes = 0;

                foreach (var entry in entries)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    if (entry.IsDirectory)
                    {
                        continue;
                    }

                    string relative = Path.GetRelativePath(normalizedPath, entry.FullPath);
                    if (IsUnderExcludedDirectory(relative))
                    {
                        continue;
                    }

                    totalBytes += entry.Length;
                }

                return totalBytes;
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex)
            {
                Logger.Warning("計算伺服器容量失敗 ({Path}): {Message}", normalizedPath, ex.Message);
                return 0L;
            }
        }, cancellationToken).ConfigureAwait(false);

        _cache[normalizedPath] = (calculatedSize, now.Add(_cacheDuration));
        return calculatedSize;
    }

    public string FormatServerSize(long bytes) => bytes <= 0 ? "-" : UnitFormatter.FormatBytes(bytes);

    public void InvalidateCache(string serverPath)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return;
        }

        string normalizedPath = Path.GetFullPath(serverPath);
        _cache.TryRemove(normalizedPath, out _);
    }

    public void ClearAllCache() => _cache.Clear();

    private static bool IsUnderExcludedDirectory(string relativePath)
    {
        ReadOnlySpan<char> span = relativePath.AsSpan();

        while (!span.IsEmpty)
        {
            int sepIndex = span.IndexOfAny('\\', '/');
            ReadOnlySpan<char> segment = sepIndex >= 0 ? span[..sepIndex] : span;

            if (ExcludedDirectoryNames.Contains(segment.ToString()))
            {
                return true;
            }

            if (sepIndex < 0)
            {
                break;
            }

            span = span[(sepIndex + 1)..];
        }

        return false;
    }
}
