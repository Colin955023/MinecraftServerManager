using System.ComponentModel;
using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

public sealed partial class JavaRuntimeDetector : IJavaRuntimeDetector
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(JavaRuntimeDetector));
    private const int MaxJavaDirectoryEntries = 128;
    private const int MaxProbeOutputChars = 16 * 1024;
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(5);
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
    private readonly IProcessRunner _processRunner;
    private readonly JavaSearchSources _sources;
    private readonly SingleFlight<bool, IReadOnlyList<JavaRuntimeInfo>> _inFlight = new();

    /// <summary>偵測世代；只有最新一輪偵測可寫入快取，避免較早完成的舊結果覆蓋 forceRefresh 的新結果</summary>
    private long _generation;

    public JavaRuntimeDetector(IProcessRunner processRunner, JavaSearchSources sources)
    {
        ArgumentNullException.ThrowIfNull(processRunner);
        ArgumentNullException.ThrowIfNull(sources);
        _processRunner = processRunner;
        _sources = sources;
    }

    public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        // 偵測由多個呼叫端共用，不繫結任一呼叫端的取消權杖；以 Task.Run 避免在 UI 執行緒做檔案 I/O
        return _inFlight.WaitAsync(
            forceRefresh,
            refresh =>
            {
                long generation = Interlocked.Increment(ref _generation);
                return Task.Run(() => DetectInternalAsync(refresh, generation, CancellationToken.None));
            },
            cancellationToken);
    }

    private async Task<IReadOnlyList<JavaRuntimeInfo>> DetectInternalAsync(
        bool forceRefresh,
        long generation,
        CancellationToken cancellationToken)
    {
        if (!forceRefresh)
        {
            var cached = await TryLoadFromCacheAsync(generation, cancellationToken).ConfigureAwait(false);
            if (cached is not null && cached.Length > 0)
            {
                return cached;
            }
        }

        var candidates = EnumerateCandidates();

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

        var sorted = Normalize(detectedBag);
        SaveToCache(sorted, generation);
        return sorted;
    }

    /// <summary>統一去重與排序：版本由小到大、同版本 64 位元優先、再依路徑</summary>
    private static JavaRuntimeInfo[] Normalize(IEnumerable<JavaRuntimeInfo> runtimes) =>
        [.. runtimes
            .DistinctBy(static item => item.ExecutablePath, StringComparer.OrdinalIgnoreCase)
            .OrderBy(static item => item.MajorVersion)
            .ThenByDescending(static item => item.Is64Bit)
            .ThenBy(static item => item.ExecutablePath, StringComparer.OrdinalIgnoreCase)];

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

            // 版本偵測逾時，避免異常 java.exe 卡住
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(ProbeTimeout);

            var process = await _processRunner.StartAsync(
                new ProcessStartSpec(probeExecutable, VersionArgs),
                cancellationToken: timeoutCts.Token).ConfigureAwait(false);

            var output = new StringBuilder();
            var outputLock = new Lock();
            ProcessExitResult result;
            await using (process.ConfigureAwait(false))
            {
                // 標準輸出與錯誤可能並行回呼；版本資訊只在前幾行，超過上限即捨棄
                process.OutputReceived += item =>
                {
                    lock (outputLock)
                    {
                        if (output.Length < MaxProbeOutputChars)
                        {
                            output.AppendLine(item.Text);
                        }
                    }
                };
                result = await process.WaitForExitAsync(timeoutCts.Token).ConfigureAwait(false);
            }

            string text;
            lock (outputLock)
            {
                text = output.ToString();
            }

            var details = JavaVersionParser.ParseDetails(text);
            return result.ExitCode == 0 && details is { MajorVersion: > 0 } parsed
                ? new JavaRuntimeInfo(
                    ExecutablePath: probeExecutable,
                    MajorVersion: parsed.MajorVersion,
                    // 以 PE 標頭判定位元數（32 位元 HotSpot 輸出常不含 "32-Bit"）
                    Is64Bit: PortableExecutableInspector.TryReadMachine(probeExecutable) is { } machine
                        ? PortableExecutableInspector.Is64Bit(machine)
                        : parsed.Is64Bit,
                    JavawPath: javawPath ?? probeExecutable,
                    Vendor: parsed.Vendor)
                : null;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            Logger.Warning("Java 版本偵測逾時: {ExecutablePath}", executablePath);
            return null;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or Win32Exception or InvalidOperationException)
        {
            Logger.Warning(ex, "讀取 Java 執行期資訊失敗: {ExecutablePath}", executablePath);
            return null;
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
