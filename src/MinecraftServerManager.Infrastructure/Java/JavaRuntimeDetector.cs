using MinecraftServerManager.Infrastructure.Logging;
using System.ComponentModel;
using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

public sealed class JavaRuntimeDetector(IProcessRunner processRunner) : IJavaRuntimeDetector
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("JavaRuntimeDetector");
    private const int MaxJavaDirectoryEntries = 128;
    private const string CacheFileName = "java_candidates_cache.json";
    private static readonly string[] CommonVendors =
    [
        "Java",
        "Microsoft",
        "Eclipse Adoptium",
        "Eclipse Foundation",
        "Zulu",
        "Amazon Corretto",
        "BellSoft",
        "Oracle",
        "Semeru"
    ];

    private static readonly string[] VersionArgs = ["-version"];
    private readonly Lock _detectLock = new();
    private Task<IReadOnlyList<JavaRuntimeInfo>>? _inFlightDetection;

    public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(processRunner);

        lock (_detectLock)
        {
            if (!forceRefresh && _inFlightDetection is not null && !_inFlightDetection.IsCompleted)
            {
                return _inFlightDetection.WaitAsync(cancellationToken);
            }

            var task = DetectInternalAsync(forceRefresh, cancellationToken);
            _inFlightDetection = task;
            return task;
        }
    }

    private async Task<IReadOnlyList<JavaRuntimeInfo>> DetectInternalAsync(
        bool forceRefresh,
        CancellationToken cancellationToken)
    {
        if (!forceRefresh)
        {
            var cached = await TryLoadFromCacheAsync(cancellationToken).ConfigureAwait(false);
            if (cached is not null && cached.Count > 0)
            {
                return cached;
            }
        }

        var candidates = EnumerateCandidates()
            .Where(c => !string.IsNullOrWhiteSpace(c))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var detectedBag = new System.Collections.Concurrent.ConcurrentBag<JavaRuntimeInfo>();
        var parallelOptions = new ParallelOptions
        {
            CancellationToken = cancellationToken,
            MaxDegreeOfParallelism = Math.Clamp(Environment.ProcessorCount, 2, 6)
        };

        await Parallel.ForEachAsync(candidates, parallelOptions, async (candidate, ct) =>
        {
            var runtime = await TryReadRuntimeAsync(candidate, ct).ConfigureAwait(false);
            if (runtime is not null)
            {
                detectedBag.Add(runtime);
            }
        }).ConfigureAwait(false);

        var sorted = detectedBag
            .GroupBy(item => item.ExecutablePath, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .OrderBy(item => item.MajorVersion)
            .ThenByDescending(item => item.Is64Bit)
            .ThenBy(item => item.ExecutablePath, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        SaveToCache(sorted);
        return sorted;
    }

    public async Task<JavaRuntimeInfo?> FindBestMatchAsync(
        int targetMajor,
        CancellationToken cancellationToken = default)
    {
        var runtimes = await DetectAsync(cancellationToken: cancellationToken).ConfigureAwait(false);

        // 嚴格精確匹配目標 Java major 版本
        // 1. 完全符合且為 64 位元
        var exact64 = runtimes.FirstOrDefault(r => r.MajorVersion == targetMajor && r.Is64Bit);
        if (exact64 is not null)
        {
            return exact64;
        }

        // 2. 完全符合（32 位元）
        var exact = runtimes.FirstOrDefault(r => r.MajorVersion == targetMajor);
        if (exact is not null)
        {
            return exact;
        }

        // 3. 找不到完全匹配的版本，回傳 null
        return null;
    }

    /// <summary>
    /// 解析系統 PATH 環境變數中的所有有效目錄路徑
    /// </summary>
    private static List<string> EnumeratePathDirectories()
    {
        string? pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathEnv))
        {
            return [];
        }

        var list = new List<string>();
        ReadOnlySpan<char> span = pathEnv.AsSpan();
        while (!span.IsEmpty)
        {
            int sepIndex = span.IndexOf(Path.PathSeparator);
            ReadOnlySpan<char> folderSpan = (sepIndex >= 0 ? span[..sepIndex] : span).Trim();
            span = sepIndex >= 0 ? span[(sepIndex + 1)..] : [];

            if (!folderSpan.IsEmpty)
            {
                list.Add(folderSpan.ToString());
            }
        }

        return list;
    }

    /// <summary>
    /// 搜尋系統 PATH 環境變數中的第一個有效 java.exe 絕對路徑
    /// </summary>
    public static string? FindSystemJavaExecutable()
    {
        foreach (string folder in EnumeratePathDirectories())
        {
            try
            {
                string candidate = Path.Combine(folder, "java.exe");
                if (SafeFileSystem.FileExists(candidate))
                {
                    return candidate;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning("檢查 PATH 中的 Java 候選路徑異常: {Message}", ex.Message);
            }
        }

        return null;
    }

    private async Task<JavaRuntimeInfo?> TryReadRuntimeAsync(
        string executablePath,
        CancellationToken cancellationToken)
    {
        try
        {
            string probeExecutable = executablePath;
            string? javawPath = null;

            string fileName = Path.GetFileName(executablePath);
            string? directory = Path.GetDirectoryName(executablePath);

            if (string.Equals(fileName, "javaw.exe", StringComparison.OrdinalIgnoreCase))
            {
                javawPath = executablePath;
                if (!string.IsNullOrEmpty(directory))
                {
                    string consoleExe = Path.Combine(directory, "java.exe");
                    if (SafeFileSystem.FileExists(consoleExe))
                    {
                        probeExecutable = consoleExe;
                    }
                }
            }
            else if (string.Equals(fileName, "java.exe", StringComparison.OrdinalIgnoreCase))
            {
                if (!string.IsNullOrEmpty(directory))
                {
                    string wExe = Path.Combine(directory, "javaw.exe");
                    if (SafeFileSystem.FileExists(wExe))
                    {
                        javawPath = wExe;
                    }
                }
            }

            var process = await processRunner.StartAsync(
                new ProcessStartSpec(probeExecutable, VersionArgs),
                cancellationToken).ConfigureAwait(false);

            var output = new StringBuilder();
            ProcessExitResult result;
            await using (process.ConfigureAwait(false))
            {
                process.OutputReceived += item => output.AppendLine(item.Text);
                result = await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            }

            var details = JavaVersionParser.ParseDetails(output.ToString());
            return result.ExitCode == 0 && details is { MajorVersion: > 0 } parsed
                ? new JavaRuntimeInfo(
                    ExecutablePath: probeExecutable,
                    MajorVersion: parsed.MajorVersion,
                    Is64Bit: parsed.Is64Bit,
                    JavawPath: javawPath ?? probeExecutable,
                    Vendor: parsed.Vendor)
                : null;
        }
        catch (FileNotFoundException)
        {
            return null;
        }
        catch (Win32Exception)
        {
            return null;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
    }

    private static HashSet<string> EnumerateCandidates()
    {
        var candidates = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        string? javaHome = Environment.GetEnvironmentVariable("JAVA_HOME");
        if (!string.IsNullOrWhiteSpace(javaHome))
        {
            AddCandidate(candidates, Path.Combine(javaHome, "bin", "java.exe"));
        }

        foreach (string folder in EnumeratePathDirectories())
        {
            AddCandidate(candidates, Path.Combine(folder, "java.exe"));
        }

        foreach (string root in GetJavaRoots())
        {
            foreach (string vendor in CommonVendors)
            {
                string vendorRoot = Path.Combine(root, vendor);
                IReadOnlyList<FileSystemEntry> entries;
                try
                {
                    entries = SafeFileSystem.ListBoundedDirectory(
                        vendorRoot,
                        maxEntries: MaxJavaDirectoryEntries,
                        maxTotalBytes: 1);
                }
                catch (IOException)
                {
                    continue;
                }

                foreach (var entry in entries.Where(static item => item.IsDirectory))
                {
                    AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "java.exe"));
                }
            }
        }

        // 使用者目錄
        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!string.IsNullOrWhiteSpace(userProfile))
        {
            string jdksDir = Path.Combine(userProfile, ".jdks");
            if (SafeFileSystem.DirectoryExists(jdksDir))
            {
                try
                {
                    var entries = SafeFileSystem.ListBoundedDirectory(jdksDir, maxEntries: MaxJavaDirectoryEntries, maxTotalBytes: 1);
                    foreach (var entry in entries.Where(static e => e.IsDirectory))
                    {
                        AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "java.exe"));
                    }
                }
                catch (IOException ex)
                {
                    Logger.Warning("列舉 JDK 目錄失敗: {0}", ex.Message);
                }
            }
        }

        return candidates;
    }

    private static HashSet<string> GetJavaRoots()
    {
        var roots = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        AddRoot(roots, Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles));
        AddRoot(roots, Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86));
        AddRoot(roots, Environment.GetEnvironmentVariable("ProgramW6432"));
        return roots;
    }

    private static void AddCandidate(HashSet<string> candidates, string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path))
        {
            return;
        }

        if (IsIgnoredJavaPath(path) || IsReparseOrJunctionPath(path) || IsShimLauncher(path))
        {
            return;
        }

        string resolved = ResolveActualExecutablePath(path);
        if (SafeFileSystem.FileExists(resolved) && !IsIgnoredJavaPath(resolved) && !IsReparseOrJunctionPath(resolved) && !IsShimLauncher(resolved))
        {
            candidates.Add(resolved);
        }
    }

    private static bool IsIgnoredJavaPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return true;
        }

        if (path.Contains(@"\Oracle\Java\javapath", StringComparison.OrdinalIgnoreCase) ||
            path.Contains(@"\Oracle\Java\java8path", StringComparison.OrdinalIgnoreCase) ||
            path.Contains(@"\Common Files\Oracle\Java\", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return false;
    }

    private static bool IsReparseOrJunctionPath(string path)
    {
        try
        {
            if (SafeFileSystem.IsReparsePoint(path))
            {
                return true;
            }

            string? dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir) && SafeFileSystem.IsReparsePoint(dir))
            {
                return true;
            }

            return false;
        }
        catch
        {
            return true;
        }
    }

    private static bool IsShimLauncher(string path)
    {
        try
        {
            if (!SafeFileSystem.FileExists(path))
            {
                return false;
            }

            var vi = System.Diagnostics.FileVersionInfo.GetVersionInfo(path);
            if (string.Equals(vi.OriginalFilename, "shimconsole.exe", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(vi.OriginalFilename, "shim.exe", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(vi.InternalName, "Shim Console Launcher", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("檢查 Shim 可執行檔資訊失敗: {0}", ex.Message);
        }

        return false;
    }

    private static string ResolveActualExecutablePath(string path)
    {
        try
        {
            string full = Path.GetFullPath(path);
            if (!SafeFileSystem.FileExists(full))
            {
                return full;
            }

            string? targetPath = SafeFileSystem.ResolveFileLinkTarget(full);
            if (targetPath is not null && SafeFileSystem.FileExists(targetPath))
            {
                return targetPath;
            }

            return full;
        }
        catch
        {
            return path;
        }
    }

    private static void AddRoot(HashSet<string> roots, string? path)
    {
        if (!string.IsNullOrWhiteSpace(path) && SafeFileSystem.DirectoryExists(path))
        {
            roots.Add(path);
        }
    }

    private async Task<List<JavaRuntimeInfo>?> TryLoadFromCacheAsync(CancellationToken cancellationToken)
    {
        try
        {
            string cachePath = Path.Combine(RuntimePaths.GetVersionCacheDir(), CacheFileName);
            if (!SafeFileSystem.FileExists(cachePath))
            {
                return null;
            }

            string content = await SafeFileSystem.ReadAllTextAsync(cachePath, Encoding.UTF8, cancellationToken: cancellationToken).ConfigureAwait(false);
            var cacheData = JsonCodec.Deserialize<JavaCachePayload>(content);
            if (cacheData?.Candidates is null or { Count: 0 })
            {
                return null;
            }

            var validRuntimes = new List<JavaRuntimeInfo>();
            bool hadInvalidEntries = false;
            foreach (var item in cacheData.Candidates)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!string.IsNullOrWhiteSpace(item.Path) &&
                    Path.IsPathRooted(item.Path) &&
                    !string.Equals(Path.GetFileName(item.Path), item.Path, StringComparison.OrdinalIgnoreCase) &&
                    SafeFileSystem.FileExists(item.Path) &&
                    !IsIgnoredJavaPath(item.Path) &&
                    !IsReparseOrJunctionPath(item.Path) &&
                    !IsShimLauncher(item.Path))
                {
                    try
                    {
                        FileSystemMetadata fileInfo = SafeFileSystem.GetFileMetadata(item.Path);
                        if (item.LastWriteTimeUtcTicks > 0 &&
                            fileInfo.LastWriteTimeUtc.Ticks == item.LastWriteTimeUtcTicks &&
                            fileInfo.Length == item.FileSizeBytes &&
                            item.MajorVersion > 0)
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
                        Logger.Warning("讀取 Java 快取檔案中繼資料失敗: {0}", ex.Message);
                    }

                    using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                    timeoutCts.CancelAfter(TimeSpan.FromSeconds(3));

                    try
                    {
                        var runtime = await TryReadRuntimeAsync(item.Path, timeoutCts.Token).ConfigureAwait(false);
                        if (runtime is not null)
                        {
                            validRuntimes.Add(runtime);
                        }
                        else
                        {
                            hadInvalidEntries = true;
                        }
                    }
                    catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
                    {
                        hadInvalidEntries = true;
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        Logger.Warning("讀取 Java 執行期資訊失敗: {0}", ex.Message);
                        hadInvalidEntries = true;
                    }
                }
                else
                {
                    hadInvalidEntries = true;
                }
            }

            if (validRuntimes.Count == 0)
            {
                return null;
            }

            var deduped = validRuntimes
                .GroupBy(static r => r.ExecutablePath, StringComparer.OrdinalIgnoreCase)
                .Select(static g => g.First())
                .ToList();

            if (hadInvalidEntries || deduped.Count != validRuntimes.Count)
            {
                SaveToCache(deduped);
            }

            return deduped;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static void SaveToCache(IReadOnlyList<JavaRuntimeInfo> runtimes)
    {
        try
        {
            string cacheDir = RuntimePaths.GetVersionCacheDir();
            SafeFileSystem.CreateDirectory(cacheDir);
            string cachePath = Path.Combine(cacheDir, CacheFileName);

            var entries = runtimes
                .Where(static r => !string.IsNullOrWhiteSpace(r.ExecutablePath) &&
                            Path.IsPathRooted(r.ExecutablePath) &&
                            !string.Equals(Path.GetFileName(r.ExecutablePath), r.ExecutablePath, StringComparison.OrdinalIgnoreCase) &&
                            SafeFileSystem.FileExists(r.ExecutablePath))
                .GroupBy(static r => r.ExecutablePath, StringComparer.OrdinalIgnoreCase)
                .Select(static g => g.First())
                .OrderBy(static r => r.MajorVersion)
                .ThenBy(static r => r.ExecutablePath, StringComparer.OrdinalIgnoreCase)
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
                        Logger.Warning("取得 Java 檔案中繼資料失敗: {0}", ex.Message);
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

            string json = JsonCodec.Serialize(payload, indented: true);
            AtomicFileWriter.WriteText(cachePath, json);
        }
        catch (Exception)
        {
            // 快取寫入失敗不影響主要功能
        }
    }
}

internal sealed record JavaCacheEntry(
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("major")] int MajorVersion,
    [property: JsonPropertyName("is64Bit")] bool Is64Bit = true,
    [property: JsonPropertyName("javawPath")] string? JavawPath = null,
    [property: JsonPropertyName("vendor")] string? Vendor = null,
    [property: JsonPropertyName("lastWriteTicks")] long LastWriteTimeUtcTicks = 0,
    [property: JsonPropertyName("fileSize")] long FileSizeBytes = 0);

internal sealed record JavaCachePayload(
    [property: JsonPropertyName("candidates")] IReadOnlyList<JavaCacheEntry> Candidates);
