using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

public sealed partial class JavaRuntimeDetector
{
    private async Task<JavaRuntimeInfo[]?> TryLoadFromCacheAsync(long generation, CancellationToken cancellationToken)
    {
        try
        {
            string cachePath = Path.Combine(_sources.CacheDirectory, CacheFileName);
            if (!SafeFileSystem.FileExists(cachePath))
            {
                return null;
            }

            var cacheData = await JsonCodec.ReadFileAsync<JavaCachePayload>(cachePath, cancellationToken).ConfigureAwait(false);
            if (cacheData?.Candidates is null or { Count: 0 })
            {
                return null;
            }

            var validRuntimes = new List<JavaRuntimeInfo>();
            bool cacheChanged = false;
            foreach (var item in cacheData.Candidates)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!string.IsNullOrWhiteSpace(item.Path) &&
                    Path.IsPathFullyQualified(item.Path) &&
                    SafeFileSystem.FileExists(item.Path) &&
                    !IsIgnoredJavaPath(item.Path))
                {
                    try
                    {
                        FileSystemMetadata fileInfo = SafeFileSystem.GetFileMetadata(item.Path);
                        if (item.LastWriteTimeUtcTicks > 0 &&
                            fileInfo.LastWriteTimeUtc.Ticks == item.LastWriteTimeUtcTicks &&
                            fileInfo.Length == item.FileSizeBytes &&
                            item.MajorVersion > 0 &&
                            IsValidJavawPath(item.JavawPath))
                        {
                            validRuntimes.Add(new JavaRuntimeInfo(
                                item.Path,
                                item.MajorVersion,
                                item.Is64Bit,
                                item.JavawPath,
                                item.Vendor ?? string.Empty));
                            continue;
                        }
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        Logger.Warning(ex, "讀取 Java 快取檔案中繼資料失敗: {Path}", item.Path);
                    }

                    // 檔案已變更或快取欄位無效：重新偵測，結果不論成敗都需回寫快取
                    cacheChanged = true;
                    if (IsShimLauncher(item.Path))
                    {
                        continue;
                    }

                    if (await TryReadRuntimeAsync(item.Path, cancellationToken).ConfigureAwait(false) is { } runtime)
                    {
                        validRuntimes.Add(runtime);
                    }
                }
                else
                {
                    cacheChanged = true;
                }
            }

            if (validRuntimes.Count == 0)
            {
                return null;
            }

            var normalized = Normalize(validRuntimes);
            if (cacheChanged || normalized.Length != validRuntimes.Count)
            {
                SaveToCache(normalized, generation);
            }

            return normalized;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取 Java 偵測快取失敗，改為重新偵測");
            return null;
        }
    }

    /// <summary>javaw 路徑須為完整路徑且檔案存在</summary>
    private static bool IsValidJavawPath(string? javawPath) =>
        !string.IsNullOrWhiteSpace(javawPath) &&
        Path.IsPathFullyQualified(javawPath) &&
        SafeFileSystem.FileExists(javawPath);

    private void SaveToCache(IReadOnlyList<JavaRuntimeInfo> runtimes, long generation)
    {
        // 已有較新一輪偵測開始時，捨棄本輪結果
        if (Volatile.Read(ref _generation) != generation)
        {
            Logger.Information("Java 偵測結果已過時，略過寫入快取 (世代 {Generation})", generation);
            return;
        }

        try
        {
            string cacheDir = _sources.CacheDirectory;
            SafeFileSystem.CreateDirectory(cacheDir);
            string cachePath = Path.Combine(cacheDir, CacheFileName);

            // runtimes 已由 Normalize 去重排序
            var entries = runtimes
                .Where(static r => !string.IsNullOrWhiteSpace(r.ExecutablePath) &&
                            Path.IsPathFullyQualified(r.ExecutablePath))
                .Select(static r =>
                {
                    long lastWriteTicks = 0;
                    long fileSize = 0;
                    try
                    {
                        FileSystemMetadata fi = SafeFileSystem.GetFileMetadata(r.ExecutablePath);
                        lastWriteTicks = fi.LastWriteTimeUtc.Ticks;
                        fileSize = fi.Length;
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        Logger.Warning(ex, "取得 Java 檔案中繼資料失敗: {Path}", r.ExecutablePath);
                    }
                    return new JavaCacheEntry(
                        r.ExecutablePath,
                        r.MajorVersion,
                        r.Is64Bit,
                        r.JavawPath,
                        r.Vendor,
                        lastWriteTicks,
                        fileSize);
                })
                .ToList();

            var payload = new JavaCachePayload(Candidates: entries);

            AtomicFileWriter.WriteJson(cachePath, payload);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "寫入 Java 偵測快取失敗");
        }
    }
}
