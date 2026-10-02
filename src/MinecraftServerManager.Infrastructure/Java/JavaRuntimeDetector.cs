using System.ComponentModel;
using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

public sealed class JavaRuntimeDetector(IProcessRunner processRunner) : IJavaRuntimeDetector
{
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

    public async Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(processRunner);

        if (!forceRefresh)
        {
            var cached = TryLoadFromCache();
            if (cached is not null && cached.Count > 0)
            {
                return cached;
            }
        }

        var detected = new List<JavaRuntimeInfo>();
        foreach (string candidate in EnumerateCandidates())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var runtime = await TryReadRuntimeAsync(candidate, cancellationToken).ConfigureAwait(false);
            if (runtime is not null && detected.All(item =>
                    !string.Equals(item.ExecutablePath, runtime.ExecutablePath, StringComparison.OrdinalIgnoreCase)))
            {
                detected.Add(runtime);
            }
        }

        var sorted = detected
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
                    if (File.Exists(consoleExe))
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
                    if (File.Exists(wExe))
                    {
                        javawPath = wExe;
                    }
                }
            }

            var process = await processRunner.StartAsync(
                new ProcessStartSpec(probeExecutable, ["-version"]),
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
            AddCandidate(candidates, Path.Combine(javaHome, "bin", "javaw.exe"));
        }

        candidates.Add("java.exe");

        string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        ReadOnlySpan<char> pathSpan = pathEnv.AsSpan();
        while (!pathSpan.IsEmpty)
        {
            int sepIndex = pathSpan.IndexOf(Path.PathSeparator);
            ReadOnlySpan<char> segment = (sepIndex >= 0 ? pathSpan[..sepIndex] : pathSpan).Trim();
            pathSpan = sepIndex >= 0 ? pathSpan[(sepIndex + 1)..] : [];

            if (segment.IsEmpty)
            {
                continue;
            }

            string segmentStr = segment.ToString();
            AddCandidate(candidates, Path.Combine(segmentStr, "java.exe"));
            AddCandidate(candidates, Path.Combine(segmentStr, "javaw.exe"));
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

                foreach (var entry in entries.Where(item => item.IsDirectory))
                {
                    AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "java.exe"));
                    AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "javaw.exe"));
                }
            }
        }

        // 使用者目錄
        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!string.IsNullOrWhiteSpace(userProfile))
        {
            string jdksDir = Path.Combine(userProfile, ".jdks");
            if (Directory.Exists(jdksDir))
            {
                try
                {
                    var entries = SafeFileSystem.ListBoundedDirectory(jdksDir, maxEntries: MaxJavaDirectoryEntries, maxTotalBytes: 1);
                    foreach (var entry in entries.Where(e => e.IsDirectory))
                    {
                        AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "java.exe"));
                        AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "javaw.exe"));
                    }
                }
                catch (IOException)
                {
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
        if (Path.IsPathRooted(path) && File.Exists(path) && !SafeFileSystem.IsReparsePoint(path))
        {
            candidates.Add(Path.GetFullPath(path));
        }
    }

    private static void AddRoot(HashSet<string> roots, string? path)
    {
        if (!string.IsNullOrWhiteSpace(path) && Directory.Exists(path))
        {
            roots.Add(path);
        }
    }

    private static List<JavaRuntimeInfo>? TryLoadFromCache()
    {
        try
        {
            string cachePath = Path.Combine(RuntimePaths.GetVersionCacheDir(), CacheFileName);
            if (!File.Exists(cachePath))
            {
                return null;
            }

            string content = File.ReadAllText(cachePath, Encoding.UTF8);
            var cacheData = JsonCodec.Deserialize<JavaCachePayload>(content);
            if (cacheData?.Candidates is null or { Count: 0 })
            {
                return null;
            }

            var validRuntimes = new List<JavaRuntimeInfo>();
            foreach (var item in cacheData.Candidates)
            {
                if (File.Exists(item.Path) && !SafeFileSystem.IsReparsePoint(item.Path))
                {
                    // 驗證實際的 Java 版本
                    try
                    {
                        using var process = new System.Diagnostics.Process
                        {
                            StartInfo = new System.Diagnostics.ProcessStartInfo
                            {
                                FileName = item.Path,
                                Arguments = "-version",
                                RedirectStandardOutput = true,
                                RedirectStandardError = true,
                                UseShellExecute = false,
                                CreateNoWindow = true
                            }
                        };
                        process.Start();
                        string output = process.StandardError.ReadToEnd() + process.StandardOutput.ReadToEnd();
                        process.WaitForExit();

                        var details = JavaVersionParser.ParseDetails(output);
                        if (details is { MajorVersion: > 0 } parsed)
                        {
                            validRuntimes.Add(new JavaRuntimeInfo(
                                ExecutablePath: item.Path,
                                MajorVersion: parsed.MajorVersion,
                                Is64Bit: parsed.Is64Bit,
                                JavawPath: null,
                                Vendor: parsed.Vendor));
                        }
                    }
                    catch
                    {
                        // 版本讀取失敗，跳過此項目
                    }
                }
                else
                {
                    // 若有快取項目失效，表示快取已過期
                    return null;
                }
            }

            return validRuntimes;
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
            Directory.CreateDirectory(cacheDir);
            string cachePath = Path.Combine(cacheDir, CacheFileName);

            // 規範化：驗證檔案存在、排除重複路徑、依 major 由小到大排序並使同 major 集中存放
            var entries = runtimes
                .Where(r => !string.IsNullOrWhiteSpace(r.ExecutablePath) && File.Exists(r.ExecutablePath))
                .GroupBy(r => r.ExecutablePath, StringComparer.OrdinalIgnoreCase)
                .Select(g => g.First())
                .OrderBy(r => r.MajorVersion)
                .ThenBy(r => r.ExecutablePath, StringComparer.OrdinalIgnoreCase)
                .Select(r => new JavaCacheEntry(r.ExecutablePath, r.MajorVersion))
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

    internal sealed record JavaCacheEntry(
        [property: JsonPropertyName("path")] string Path,
        [property: JsonPropertyName("major")] int MajorVersion);

    internal sealed record JavaCachePayload(
        [property: JsonPropertyName("candidates")] IReadOnlyList<JavaCacheEntry> Candidates);
}
