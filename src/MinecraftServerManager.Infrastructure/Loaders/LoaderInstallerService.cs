using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Frozen;
using System.Text.Json;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderInstallerService : ILoaderInstallerService
{
    private const int InstallerOutputTailLines = 20;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LoaderInstallerService));
    private static readonly SearchValues<char> HashSeparators = SearchValues.Create(" \t\r\n");
    private static readonly TimeSpan MetadataCacheTtl = TimeSpan.FromHours(1);
    private static readonly (string Name, int HexLength)[] HashAlgorithms = [(HashAlgorithmNames.Sha256, 64), (HashAlgorithmNames.Sha1, 40)];
    private static readonly FrozenSet<string> PaperDownloadHosts = TrustedHostPolicy.Hosts("fill-data.papermc.io", "api.papermc.io");
    private static readonly FrozenSet<string> VanillaDownloadHosts = TrustedHostPolicy.Hosts("piston-data.mojang.com", "launcher.mojang.com");
    private static readonly SearchValues<char> VersionTokenChars =
        SearchValues.Create("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.-_+");
    private static readonly TimeSpan OutputProgressInterval = TimeSpan.FromMilliseconds(200);

    private static readonly FrozenDictionary<LoaderKind, InstallerPolicy> Policies =
        new Dictionary<LoaderKind, InstallerPolicy>
        {
            [LoaderKind.Fabric] = new("fabric-installer-", ".jar", KeepCount: 1, new Uri("https://meta.fabricmc.net/v2/versions/installer"), TrustedHostPolicy.Hosts("maven.fabricmc.net"), PreferStable: true, ReadMetaHashes: false),
            [LoaderKind.Quilt] = new("quilt-installer-", ".jar", KeepCount: 1, new Uri("https://meta.quiltmc.org/v3/versions/installer"), TrustedHostPolicy.Hosts("maven.quiltmc.org"), PreferStable: false, ReadMetaHashes: true),
            [LoaderKind.Forge] = new("forge-", "-installer.jar", KeepCount: 5),
            [LoaderKind.NeoForge] = new("neoforge-", "-installer.jar", KeepCount: 5)
        }.ToFrozenDictionary();

    private readonly IHttpPort _httpPort;
    private readonly IProcessRunner _processRunner;
    private readonly string _cacheDir;
    private readonly string _versionCacheDir;
    private readonly ConcurrentDictionary<LoaderKind, (InstallerDescriptor Descriptor, DateTimeOffset ExpiresAtUtc)> _metadataCache = new();

    // 同一安裝器快取檔序列化下載；進行中的檔名不得被清理
    private readonly KeyedAsyncLock _downloadGates = new();
    private readonly TimeProvider _timeProvider;
    private readonly ConcurrentDictionary<string, byte> _activeInstallers = new(StringComparer.OrdinalIgnoreCase);

    public LoaderInstallerService(
        IHttpPort httpPort,
        IProcessRunner processRunner,
        string installerCacheDirectory,
        string versionCacheDirectory,
        TimeProvider timeProvider)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        ArgumentNullException.ThrowIfNull(timeProvider);
        _timeProvider = timeProvider;
        ArgumentNullException.ThrowIfNull(processRunner);
        ArgumentException.ThrowIfNullOrWhiteSpace(installerCacheDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(versionCacheDirectory);
        _httpPort = httpPort;
        _processRunner = processRunner;
        _cacheDir = SafeFileSystem.ResolveStableDirectory(installerCacheDirectory, create: true);
        _versionCacheDir = SafeFileSystem.ResolveStableDirectory(versionCacheDirectory, create: true);
    }

    /// <summary>安裝器整體逾時；測試可縮短</summary>
    internal TimeSpan InstallerTimeout { get; init; } = TimeSpan.FromMinutes(30);

    public async Task<string> InstallLoaderAsync(
        LoaderKind loader,
        string minecraftVersion,
        string loaderVersion,
        string serverDirectory,
        string javaExecutablePath,
        IProgress<LoaderInstallProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(minecraftVersion);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);

        if (loader == LoaderKind.Paper)
        {
            return await InstallPaperAsync(minecraftVersion, loaderVersion, stableServerDir, progress, cancellationToken).ConfigureAwait(false);
        }

        int lastPct = 0;
        void SafeReport(LoaderInstallPhase phase, string message, int pct)
        {
            lastPct = Math.Max(lastPct, pct);
            progress?.Report(new LoaderInstallProgress(phase, message, Math.Clamp(lastPct, 0, 100)));
        }

        // 只有 Fabric 與 Quilt 需先準備原版 server.jar
        if (loader is LoaderKind.Fabric or LoaderKind.Quilt)
        {
            SafeReport(LoaderInstallPhase.VanillaPrepare, "正在準備原版伺服器檔案...", 5);
            string serverJarPath = Path.Combine(stableServerDir, ServerDefaults.ServerJarFileName);
            if (!SafeFileSystem.FileExists(serverJarPath) || SafeFileSystem.GetFileLength(serverJarPath) == 0)
            {
                IProgress<LoaderInstallProgress>? vanillaProgress = progress is null ? null : new SynchronousProgress<LoaderInstallProgress>(vp =>
                {
                    int mapped = ProgressMapping.Map(vp.PercentCompleted, 100, 0, 35); // 0% ~ 35%
                    SafeReport(LoaderInstallPhase.VanillaPrepare, vp.Message, mapped);
                });
                await EnsureVanillaServerJarAsync(minecraftVersion, stableServerDir, vanillaProgress, cancellationToken).ConfigureAwait(false);
            }
            SafeReport(LoaderInstallPhase.VanillaPrepare, "原版伺服器檔案已就緒", 35);
        }

        // 下載各 Loader Installer (35% ~ 50%)
        bool isDynamic = Policies.TryGetValue(loader, out var policy) && policy.MetaUri is not null;
        SafeReport(LoaderInstallPhase.Downloading, isDynamic ? $"正在查詢 {loader} 最新安裝器版本..." : $"正在下載 {loader} 安裝器...", 36);
        string installerJarPath = await DownloadInstallerJarAsync(
            loader,
            minecraftVersion,
            loaderVersion,
            () => SafeReport(LoaderInstallPhase.Downloading, $"正在下載 {loader} 安裝器...", 38),
            cancellationToken).ConfigureAwait(false);
        SafeReport(LoaderInstallPhase.Downloading, $"{loader} 安裝器下載完成", 50);

        // 組合啟動參數
        SafeReport(LoaderInstallPhase.Installing, $"正在執行 {loader} 伺服器安裝...", 52);
        var spec = BuildProcessStartSpec(loader, minecraftVersion, loaderVersion, installerJarPath, stableServerDir, javaExecutablePath);

        // 執行安裝流程 (52% ~ 95%)：提前備妥處理常式避免漏接啟動首行輸出
        var tracker = new InstallerProgressEstimator();
        var outputTail = new Queue<string>(InstallerOutputTailLines);
        var outputLock = new Lock();
        var progressThrottle = new ProgressThrottle(OutputProgressInterval, _timeProvider);

        var process = await _processRunner.StartAsync(spec, cancellationToken: cancellationToken).ConfigureAwait(false);
        process.OutputReceived += output =>
        {
            int mapped;
            bool shouldReport;
            lock (outputLock)
            {
                if (outputTail.Count == InstallerOutputTailLines)
                {
                    outputTail.Dequeue();
                }

                outputTail.Enqueue(output.Text);
                int estimated = tracker.FeedOutput(output.Text);
                mapped = ProgressMapping.Map(estimated, 100, 52, 95);

                // 安裝器輸出量大；百分比未變時節流回報，避免 UI 佇列堆積
                shouldReport = progressThrottle.ShouldReport(mapped);
            }

            if (shouldReport)
            {
                SafeReport(LoaderInstallPhase.Installing, output.Text, mapped);
            }
        };

        await using (process.ConfigureAwait(false))
        {

            // 安裝器卡住時不可無限等待；逾時後離開 using 會強制終止行程樹
            using var installTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            installTimeout.CancelAfter(InstallerTimeout);
            ProcessExitResult exitResult;
            try
            {
                exitResult = await process.WaitForExitAsync(installTimeout.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException($"{loader} 安裝器超過 {InstallerTimeout.TotalMinutes:0} 分鐘未完成，已中止");
            }

            if (exitResult.ExitCode != 0)
            {
                string tail;
                string lastLine;
                lock (outputLock)
                {
                    tail = string.Join(Environment.NewLine, outputTail);
                    lastLine = outputTail.LastOrDefault(static line => !string.IsNullOrWhiteSpace(line)) ?? string.Empty;
                }

                Logger.Warning("{Loader} 安裝器結束代碼 {ExitCode}，最後輸出：{Output}", loader, exitResult.ExitCode, tail);
                throw new InvalidOperationException(lastLine.Length == 0
                    ? $"{loader} 安裝失敗，行程結束代碼：{exitResult.ExitCode}"
                    : $"{loader} 安裝失敗，行程結束代碼：{exitResult.ExitCode}\n{lastLine}");
            }
        }

        // 探索主要啟動檔案
        SafeReport(LoaderInstallPhase.Finalizing, "正在確認伺服器啟動檔案...", 96);
        string launchTarget = ServerLaunchTargetResolver.ResolveLaunchTarget(stableServerDir, loader);

        SafeReport(LoaderInstallPhase.Completed, "安裝完成", 100);
        return launchTarget;
    }

    private async Task<string> InstallPaperAsync(
        string minecraftVersion,
        string loaderVersion,
        string serverDirectory,
        IProgress<LoaderInstallProgress>? progress,
        CancellationToken cancellationToken)
    {
        progress?.Report(new LoaderInstallProgress(LoaderInstallPhase.Fetching, "正在取得 PaperMC 伺服器下載資訊...", 10));

        Uri buildEndpoint = string.IsNullOrWhiteSpace(loaderVersion) || loaderVersion.Equals("latest", StringComparison.OrdinalIgnoreCase)
            ? MojangVersionCatalog.PaperBuildUri(minecraftVersion, null)
            : MojangVersionCatalog.PaperBuildUri(minecraftVersion, loaderVersion);

        var buildResponse = await _httpPort.GetJsonDocumentAsync(buildEndpoint, cancellationToken).ConfigureAwait(false);
        if (!buildResponse.IsSuccess || buildResponse.Payload is null)
        {
            throw new InvalidOperationException($"無法取得 PaperMC {minecraftVersion} 的建置下載資訊");
        }

        string? rawDownloadUrl;
        string? fileName;
        string? sha256;
        using (buildResponse.Payload)
        {
            (rawDownloadUrl, fileName, sha256) = ExtractPaperDownloadInfo(buildResponse.Payload.RootElement);
        }

        if (string.IsNullOrEmpty(rawDownloadUrl))
        {
            throw new InvalidOperationException($"找不到 PaperMC {minecraftVersion} 的伺服器下載連結");
        }

        // 伺服器核心會以 java 執行：僅接受官方網域且須附 SHA-256
        if (!TrustedHostPolicy.TryCreate(rawDownloadUrl, PaperDownloadHosts, out Uri? downloadUri))
        {
            throw new InvalidOperationException($"PaperMC 下載連結不是官方來源，已拒絕下載：{rawDownloadUrl}");
        }

        if (string.IsNullOrEmpty(sha256) || !HashCalculator.IsHexDigest(sha256, 64))
        {
            throw new InvalidOperationException($"PaperMC {minecraftVersion} 缺少有效 SHA-256，已拒絕下載");
        }

        // API 回傳檔名不可信任：僅取檔名部分且須為 .jar，並確認位於伺服器目錄內
        string? apiJarName = string.IsNullOrWhiteSpace(fileName) ? null : Path.GetFileName(fileName);
        string targetJarName = apiJarName is not null && ModHelpers.IsJarFileName(apiJarName) ? apiJarName : "paper.jar";
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string targetJarPath = Path.Combine(stableServerDir, targetJarName);
        if (!SafeFileSystem.IsPathWithin(stableServerDir, targetJarPath, strict: false))
        {
            throw new InvalidOperationException($"PaperMC 檔名超出伺服器目錄邊界：{fileName}");
        }

        await TrustedArtifactDownloader.DownloadVerifiedAsync(
            _httpPort,
            downloadUri,
            targetJarPath,
            sha256,
            HashAlgorithmNames.Sha256,
            progress,
            20,
            95,
            targetJarName,
            cancellationToken).ConfigureAwait(false);

        progress?.Report(new LoaderInstallProgress(LoaderInstallPhase.Completed, "PaperMC 伺服器核心下載完成", 100));
        return targetJarName;
    }

    private static (string? DownloadUrl, string? FileName, string? Sha256) ExtractPaperDownloadInfo(JsonElement root)
    {
        if (!MojangVersionCatalog.TryGetPaperDownload(root, out var item))
        {
            return (null, null, null);
        }

        string? sha256 = item.TryGetProperty("checksums", JsonValueKind.Object, out var checksums)
            ? checksums.GetStringOrNull("sha256")
            : null;
        return (item.GetStringOrNull("url"), item.GetStringOrNull("name"), sha256);
    }

    private async Task<string> EnsureVanillaServerJarAsync(
        string minecraftVersion,
        string serverDirectory,
        IProgress<LoaderInstallProgress>? progress,
        CancellationToken cancellationToken)
    {
        progress?.Report(new LoaderInstallProgress(LoaderInstallPhase.Fetching, "正在取得官方原版伺服器下載資訊...", 10));

        string? versionMetaUrl = MojangVersionCatalog.TryGetCachedPackageUrl(_versionCacheDir, minecraftVersion);
        if (string.IsNullOrEmpty(versionMetaUrl))
        {
            var manifest = await MojangVersionCatalog.FetchManifestAsync(_httpPort, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("無法取得 Minecraft 官方版本清單");
            versionMetaUrl = manifest.FirstOrDefault(v => string.Equals(v.Version, minecraftVersion, StringComparison.Ordinal))?.Url;
        }

        if (!MojangVersionCatalog.IsOfficialPackageUrl(versionMetaUrl))
        {
            throw new InvalidOperationException($"找不到 Minecraft {minecraftVersion} 的官方下載詮釋資料");
        }

        var metaResp = await _httpPort.GetJsonDocumentAsync(new Uri(versionMetaUrl), cancellationToken).ConfigureAwait(false);
        if (!metaResp.IsSuccess || metaResp.Payload is null)
        {
            throw new InvalidOperationException($"無法取得 Minecraft {minecraftVersion} 的版本詮釋資料");
        }

        string? serverDownloadUrl;
        string? expectedSha1;
        using (metaResp.Payload)
        {
            (serverDownloadUrl, expectedSha1) = ExtractServerDownloadInfo(metaResp.Payload);
        }

        if (string.IsNullOrEmpty(serverDownloadUrl))
        {
            throw new InvalidOperationException($"找不到 Minecraft {minecraftVersion} 的 server.jar 下載連結");
        }

        if (!TrustedHostPolicy.TryCreate(serverDownloadUrl, VanillaDownloadHosts, out Uri? serverDownloadUri))
        {
            throw new InvalidOperationException($"server.jar 下載連結不是 Mojang 官方來源，已拒絕下載：{serverDownloadUrl}");
        }

        if (string.IsNullOrEmpty(expectedSha1) || !HashCalculator.IsHexDigest(expectedSha1, 40))
        {
            throw new InvalidOperationException($"Minecraft {minecraftVersion} 的 server.jar 缺少有效 SHA-1，已拒絕下載");
        }

        string targetJar = Path.Combine(serverDirectory, ServerDefaults.ServerJarFileName);
        await TrustedArtifactDownloader.DownloadVerifiedAsync(
            _httpPort,
            serverDownloadUri,
            targetJar,
            expectedSha1,
            HashAlgorithmNames.Sha1,
            progress,
            30,
            95,
            "原版 server.jar",
            cancellationToken).ConfigureAwait(false);

        progress?.Report(new LoaderInstallProgress(LoaderInstallPhase.Completed, "原版 server.jar 準備完成", 100));
        return ServerDefaults.ServerJarFileName;
    }

    private sealed record InstallerPolicy(
        string Prefix,
        string Suffix,
        int KeepCount,
        Uri? MetaUri = null,
        FrozenSet<string>? AllowedHosts = null,
        bool PreferStable = false,
        bool ReadMetaHashes = false);

    private sealed record InstallerDescriptor(Uri Uri, string FileName, string? ExpectedHash = null, string? HashAlgorithm = null);

    private static ProcessStartSpec BuildProcessStartSpec(
        LoaderKind loader,
        string minecraftVersion,
        string loaderVersion,
        string installerJarPath,
        string serverDirectory,
        string javaExecutablePath)
    {
        var args = new List<string>
        {
            "-Dfile.encoding=UTF-8",
            "-Dsun.stdout.encoding=UTF-8",
            "-Dsun.stderr.encoding=UTF-8",
            "-jar",
            installerJarPath
        };

        switch (loader)
        {
            case LoaderKind.Fabric:
                args.Add("server");
                args.Add("-mcversion");
                args.Add(minecraftVersion);
                if (!string.IsNullOrWhiteSpace(loaderVersion))
                {
                    args.Add("-loader");
                    args.Add(loaderVersion);
                }
                args.Add("-dir");
                args.Add(serverDirectory);
                break;
            case LoaderKind.Quilt:
                args.Add("install");
                args.Add("server");
                args.Add(minecraftVersion);
                if (!string.IsNullOrWhiteSpace(loaderVersion))
                {
                    args.Add(loaderVersion);
                }
                args.Add($"--install-dir={serverDirectory}");
                break;
            case LoaderKind.Forge:
            case LoaderKind.NeoForge:
                args.Add("--installServer");
                break;
        }

        return new ProcessStartSpec(
            FileName: javaExecutablePath,
            Arguments: args,
            WorkingDirectory: serverDirectory);
    }

    private static (string? Url, string? Sha1) ExtractServerDownloadInfo(JsonDocument doc) =>
        doc.RootElement.TryGetProperty("downloads", JsonValueKind.Object, out var dl)
        && dl.TryGetProperty("server", JsonValueKind.Object, out var serverElem)
            ? (serverElem.GetStringOrNull("url"), serverElem.GetStringOrNull("sha1"))
            : (null, null);
}
