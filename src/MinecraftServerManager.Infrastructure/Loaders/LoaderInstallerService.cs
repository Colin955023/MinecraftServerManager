using MinecraftServerManager.Infrastructure.Logging;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Frozen;
using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderInstallerService(
    IHttpPort httpPort,
    IProcessRunner processRunner,
    string installerCacheDirectory) : ILoaderInstallerService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LoaderInstallerService));
    private static readonly SearchValues<char> HashSeparators = SearchValues.Create(" \t\r\n");
    private static readonly TimeSpan MetadataCacheTtl = TimeSpan.FromHours(1);
    private static readonly (string Name, int HexLength)[] HashAlgorithms = [("sha256", 64), ("sha1", 40)];

    private static readonly FrozenDictionary<LoaderKind, InstallerPolicy> Policies =
        new Dictionary<LoaderKind, InstallerPolicy>
        {
            [LoaderKind.Fabric] = new("fabric-installer-", ".jar", KeepCount: 1, new Uri("https://meta.fabricmc.net/v2/versions/installer"), "maven.fabricmc.net", PreferStable: true, ReadMetaHashes: false),
            [LoaderKind.Quilt] = new("quilt-installer-", ".jar", KeepCount: 1, new Uri("https://meta.quiltmc.org/v3/versions/installer"), "maven.quiltmc.org", PreferStable: false, ReadMetaHashes: true),
            [LoaderKind.Forge] = new("forge-", "-installer.jar", KeepCount: 5),
            [LoaderKind.NeoForge] = new("neoforge-", "-installer.jar", KeepCount: 5)
        }.ToFrozenDictionary();

    /// <summary>安裝器整體逾時；測試可縮短</summary>
    internal TimeSpan InstallerTimeout { get; init; } = TimeSpan.FromMinutes(30);

    /// <summary>中繼資料快取時間來源；測試可替換</summary>
    internal TimeProvider TimeProvider { get; init; } = TimeProvider.System;

    private readonly string _cacheDir = SafeFileSystem.ResolveStableDirectory(installerCacheDirectory, create: true);
    private readonly ConcurrentDictionary<LoaderKind, (InstallerDescriptor Descriptor, DateTimeOffset ExpiresAtUtc)> _metadataCache = new();

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
        void SafeReport(string phase, string message, int pct)
        {
            lastPct = Math.Max(lastPct, pct);
            progress?.Report(new LoaderInstallProgress(phase, message, Math.Clamp(lastPct, 0, 100)));
        }

        // 只有 Fabric 與 Quilt 需先準備原版 server.jar
        if (loader is LoaderKind.Fabric or LoaderKind.Quilt)
        {
            SafeReport("vanilla_prepare", "正在準備原版伺服器檔案...", 5);
            string serverJarPath = Path.Combine(stableServerDir, "server.jar");
            if (!SafeFileSystem.FileExists(serverJarPath))
            {
                IProgress<LoaderInstallProgress>? vanillaProgress = progress is null ? null : new SynchronousProgress<LoaderInstallProgress>(vp =>
                {
                    int mapped = (int)(vp.PercentCompleted * 0.35); // 0% ~ 35%
                    SafeReport("vanilla_prepare", vp.Message, mapped);
                });
                await EnsureVanillaServerJarAsync(minecraftVersion, stableServerDir, vanillaProgress, cancellationToken).ConfigureAwait(false);
            }
            SafeReport("vanilla_prepare", "原版伺服器檔案已就緒", 35);
        }

        // 下載各 Loader Installer (35% ~ 50%)
        bool isDynamic = Policies.TryGetValue(loader, out var policy) && policy.MetaUri is not null;
        SafeReport("downloading", isDynamic ? $"正在查詢 {loader} 最新安裝器版本..." : $"正在下載 {loader} 安裝器...", 36);
        string installerJarPath = await DownloadInstallerJarAsync(
            loader,
            minecraftVersion,
            loaderVersion,
            () => SafeReport("downloading", $"正在下載 {loader} 安裝器...", 38),
            cancellationToken).ConfigureAwait(false);
        SafeReport("downloading", $"{loader} 安裝器下載完成", 50);

        // 組合啟動參數
        SafeReport("installing", $"正在執行 {loader} 伺服器安裝...", 52);
        var spec = BuildProcessStartSpec(loader, minecraftVersion, loaderVersion, installerJarPath, stableServerDir, javaExecutablePath);

        // 執行安裝流程 (52% ~ 95%)
        var process = await processRunner.StartAsync(spec, cancellationToken).ConfigureAwait(false);
        await using (process.ConfigureAwait(false))
        {
            var tracker = new InstallerProgressEstimator();
            process.OutputReceived += output =>
            {
                int estimated = tracker.FeedOutput(output.Text);
                int mapped = 52 + (int)(estimated * 0.43); // 52% ~ 95%
                SafeReport("installing", output.Text, mapped);
            };

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
                throw new InvalidOperationException($"{loader} 安裝失敗，行程結束代碼：{exitResult.ExitCode}");
            }
        }

        // 探索主要啟動檔案
        SafeReport("finalizing", "正在確認伺服器啟動檔案...", 96);
        string launchTarget = ServerLaunchTargetResolver.ResolveLaunchTarget(stableServerDir, loader);

        SafeReport("completed", "安裝完成", 100);
        return launchTarget;
    }

    private async Task<string> InstallPaperAsync(
        string minecraftVersion,
        string loaderVersion,
        string serverDirectory,
        IProgress<LoaderInstallProgress>? progress,
        CancellationToken cancellationToken)
    {
        progress?.Report(new LoaderInstallProgress("fetching", "正在取得 PaperMC 伺服器下載資訊...", 10));

        Uri buildEndpoint = string.IsNullOrWhiteSpace(loaderVersion) || loaderVersion.Contains("最新", StringComparison.OrdinalIgnoreCase) || loaderVersion.Equals("latest", StringComparison.OrdinalIgnoreCase)
            ? MojangVersionCatalog.PaperBuildUri(minecraftVersion, null)
            : MojangVersionCatalog.PaperBuildUri(minecraftVersion, loaderVersion);

        string? buildJson = await httpPort.GetTextAsync(buildEndpoint, cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(buildJson))
        {
            throw new InvalidOperationException($"無法取得 PaperMC {minecraftVersion} 的建置下載資訊");
        }

        var (downloadUrl, fileName, sha256) = ExtractPaperDownloadInfo(buildJson);
        if (string.IsNullOrEmpty(downloadUrl))
        {
            throw new InvalidOperationException($"找不到 PaperMC {minecraftVersion} 的伺服器下載連結");
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

        progress?.Report(new LoaderInstallProgress("downloading", $"正在下載 {targetJarName}...", 20));

        var downloadResult = await httpPort.DownloadAsync(
            new Uri(downloadUrl),
            targetJarPath,
            new SynchronousProgress<HttpProgress>(p =>
            {
                int pct = p.TotalBytes > 0 ? (int)(20 + ((double)p.BytesDownloaded / p.TotalBytes * 75)) : 20;
                progress?.Report(new LoaderInstallProgress("downloading", $"正在下載 {targetJarName} ({UnitFormatter.FormatBytes(p.BytesDownloaded)})...", pct));
            }),
            expectedHash: sha256,
            expectedHashAlgorithm: "sha256",
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!downloadResult.Success)
        {
            throw new InvalidOperationException($"下載 PaperMC 核心失敗：{downloadResult.Error}");
        }

        progress?.Report(new LoaderInstallProgress("completed", "PaperMC 伺服器核心下載完成", 100));
        return targetJarName;
    }

    private static (string? DownloadUrl, string? FileName, string? Sha256) ExtractPaperDownloadInfo(string json)
    {
        using var doc = JsonCodec.ParseDocument(json);
        if (!MojangVersionCatalog.TryGetPaperDownload(doc.RootElement, out var item))
        {
            return (null, null, null);
        }

        string? url = item.TryGetProperty("url", out var u) ? u.GetString() : null;
        string? name = item.TryGetProperty("name", out var n) ? n.GetString() : null;
        string? sha256 = null;
        if (item.TryGetProperty("checksums", out var csProp) && csProp.TryGetProperty("sha256", out var shaProp))
        {
            sha256 = shaProp.GetString();
        }

        return (url, name, sha256);
    }

    private async Task<string> EnsureVanillaServerJarAsync(
        string minecraftVersion,
        string serverDirectory,
        IProgress<LoaderInstallProgress>? progress,
        CancellationToken cancellationToken)
    {
        progress?.Report(new LoaderInstallProgress("fetching", "正在取得官方原版伺服器下載資訊...", 10));

        string cacheDirectory = RuntimePaths.GetVersionCacheDir();
        string? versionMetaUrl = MojangVersionCatalog.TryGetCachedPackageUrl(cacheDirectory, minecraftVersion);
        if (string.IsNullOrEmpty(versionMetaUrl))
        {
            var manifest = await MojangVersionCatalog.FetchManifestAsync(httpPort, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("無法取得 Minecraft 官方版本清單");
            versionMetaUrl = manifest.FirstOrDefault(v => string.Equals(v.Version, minecraftVersion, StringComparison.Ordinal))?.Url;
        }

        if (string.IsNullOrEmpty(versionMetaUrl))
        {
            throw new InvalidOperationException($"找不到 Minecraft {minecraftVersion} 的官方下載詮釋資料");
        }

        var metaResp = await httpPort.GetJsonDocumentAsync(new Uri(versionMetaUrl), cancellationToken).ConfigureAwait(false);
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

        string targetJar = Path.Combine(serverDirectory, "server.jar");
        progress?.Report(new LoaderInstallProgress("downloading", "正在下載原版 server.jar...", 30));

        var downloadResult = await httpPort.DownloadAsync(
            new Uri(serverDownloadUrl),
            targetJar,
            new SynchronousProgress<HttpProgress>(p =>
            {
                int pct = ProgressMapping.Map(p.BytesDownloaded, p.TotalBytes, 30, 95);
                progress?.Report(new LoaderInstallProgress("downloading", $"正在下載原版 server.jar ({UnitFormatter.FormatBytes(p.BytesDownloaded)})...", pct));
            }),
            expectedHash: expectedSha1,
            expectedHashAlgorithm: "sha1",
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!downloadResult.Success)
        {
            throw new InvalidOperationException($"下載原版 server.jar 失敗：{downloadResult.Error}");
        }

        progress?.Report(new LoaderInstallProgress("completed", "原版 server.jar 準備完成", 100));
        return "server.jar";
    }

    private async Task<string> DownloadInstallerJarAsync(
        LoaderKind loader,
        string minecraftVersion,
        string loaderVersion,
        Action onStartDownload,
        CancellationToken cancellationToken)
    {
        bool isDynamic = Policies.TryGetValue(loader, out var policy) && policy.MetaUri is not null;
        InstallerDescriptor descriptor;
        if (isDynamic)
        {
            var (resolved, fallbackPath) = await ResolveDynamicInstallerAsync(loader, policy!, cancellationToken).ConfigureAwait(false);
            if (fallbackPath is not null)
            {
                return fallbackPath;
            }

            descriptor = resolved!;
            onStartDownload();
        }
        else
        {
            string url = loader switch
            {
                LoaderKind.Forge => $"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraftVersion}-{loaderVersion}/forge-{minecraftVersion}-{loaderVersion}-installer.jar",
                LoaderKind.NeoForge => $"https://maven.neoforged.net/releases/net/neoforged/neoforge/{loaderVersion}/neoforge-{loaderVersion}-installer.jar",
                _ => throw new NotSupportedException($"不支援的 Loader: {loader}")
            };
            var uri = new Uri(url);
            descriptor = new(uri, Path.GetFileName(uri.AbsolutePath));
        }

        string destination = Path.Combine(_cacheDir, descriptor.FileName);
        if (!SafeFileSystem.IsPathWithin(_cacheDir, destination, strict: false))
        {
            throw new InvalidOperationException($"安裝器快取路徑超出允許範圍：{descriptor.FileName}");
        }

        string hashSidecar = destination + ".sha256";

        // 快取安裝器執行前須與下載當下記錄之 SHA-256 相符，否則重新下載
        if (!await IsCachedInstallerIntactAsync(destination, hashSidecar, cancellationToken).ConfigureAwait(false))
        {
            try
            {
                await DownloadAndVerifyAsync(loader, descriptor, destination, hashSidecar, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex) when (isDynamic && ex is not OperationCanceledException)
            {
                _metadataCache.TryRemove(loader, out _);
                throw;
            }
        }

        CleanupOldInstallers(loader, destination);
        return destination;
    }

    private async Task DownloadAndVerifyAsync(
        LoaderKind loader,
        InstallerDescriptor descriptor,
        string destination,
        string hashSidecar,
        CancellationToken cancellationToken)
    {
        // 安裝器會以 java 執行：取不到雜湊即拒絕，不做未驗證下載
        string? expectedHash = descriptor.ExpectedHash;
        string expectedAlgorithm = descriptor.HashAlgorithm ?? "sha256";
        if (expectedHash is null)
        {
            foreach (var (alg, len) in HashAlgorithms)
            {
                expectedHash = await TryFetchInstallerHashAsync($"{descriptor.Uri.AbsoluteUri}.{alg}", len, cancellationToken).ConfigureAwait(false);
                if (expectedHash is not null)
                {
                    expectedAlgorithm = alg;
                    break;
                }
            }
        }

        if (expectedHash is null)
        {
            throw new InvalidOperationException($"無法取得 {loader} 安裝器的雜湊檔，已拒絕下載與執行");
        }

        var result = await httpPort.DownloadAsync(descriptor.Uri, destination, expectedHash: expectedHash, expectedHashAlgorithm: expectedAlgorithm, cancellationToken: cancellationToken).ConfigureAwait(false);
        if (!result.Success)
        {
            throw new InvalidOperationException($"下載 {loader} 安裝器失敗：{result.Error}");
        }

        string sha256 = await HashCalculator.ComputeFileHashAsync(destination, cancellationToken: cancellationToken).ConfigureAwait(false);
        await SafeFileSystem.WriteAllTextAsync(hashSidecar, sha256, cancellationToken: cancellationToken).ConfigureAwait(false);
    }

    private async Task<(InstallerDescriptor? Descriptor, string? FallbackPath)> ResolveDynamicInstallerAsync(
        LoaderKind loader,
        InstallerPolicy policy,
        CancellationToken cancellationToken)
    {
        DateTimeOffset nowUtc = TimeProvider.GetUtcNow();
        if (_metadataCache.TryGetValue(loader, out var cached) && nowUtc < cached.ExpiresAtUtc)
        {
            return (cached.Descriptor, null);
        }

        try
        {
            var response = await httpPort.GetJsonDocumentAsync(policy.MetaUri!, cancellationToken).ConfigureAwait(false);
            using var doc = response.Payload;
            if (response.IsSuccess && doc is not null && TryParseDynamicDescriptor(doc.RootElement, policy, out var descriptor))
            {
                _metadataCache[loader] = (descriptor, nowUtc.Add(MetadataCacheTtl));
                return (descriptor, null);
            }

            Logger.Warning("無法解析 {Loader} 安裝器中繼資料 (Status: {StatusCode})，改檢查本機快取", loader, response.StatusCode);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "查詢 {Loader} 最新安裝器中繼資料失敗，改檢查本機快取", loader);
        }

        string? fallbackPath = await TryFindLatestIntactCacheAsync(policy, cancellationToken).ConfigureAwait(false);
        if (fallbackPath is not null)
        {
            Logger.Warning("無法連線 {Loader} 中繼資料端點，改用本機已驗證快取：{Path}", loader, fallbackPath);
            return (null, fallbackPath);
        }

        throw new InvalidOperationException($"無法取得 {loader} 最新安裝器中繼資料，且本機無可用的已驗證快取");
    }

    private bool TryParseDynamicDescriptor(JsonElement root, InstallerPolicy policy, out InstallerDescriptor descriptor)
    {
        descriptor = default!;
        if (root.ValueKind != JsonValueKind.Array)
        {
            return false;
        }

        InstallerDescriptor? firstValid = null;
        foreach (JsonElement item in root.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object ||
                !item.TryGetProperty("url", out JsonElement urlProp) ||
                !TryValidateInstallerUri(urlProp.GetString(), policy, out Uri? uri, out string fileName))
            {
                continue;
            }

            string? expectedHash = null;
            string? expectedAlg = null;
            if (policy.ReadMetaHashes && item.TryGetProperty("hashes", out JsonElement hashes) && hashes.ValueKind == JsonValueKind.Object)
            {
                foreach (var (alg, len) in HashAlgorithms)
                {
                    if (hashes.TryGetProperty(alg, out JsonElement hp) &&
                        ExtractValidHexHash(hp.GetString(), len) is string hex)
                    {
                        expectedHash = hex;
                        expectedAlg = alg;
                        break;
                    }
                }
            }

            var candidate = new InstallerDescriptor(uri!, fileName, expectedHash, expectedAlg);
            firstValid ??= candidate;
            if (!policy.PreferStable || (item.TryGetProperty("stable", out JsonElement stable) && stable.ValueKind == JsonValueKind.True))
            {
                descriptor = candidate;
                return true;
            }
        }

        if (firstValid is null)
        {
            return false;
        }

        descriptor = firstValid;
        return true;
    }

    private bool TryValidateInstallerUri(string? rawUrl, InstallerPolicy policy, out Uri? uri, out string fileName)
    {
        uri = null;
        fileName = string.Empty;
        if (string.IsNullOrWhiteSpace(rawUrl) || !Uri.TryCreate(rawUrl.Trim(), UriKind.Absolute, out Uri? parsed))
        {
            return false;
        }

        try
        {
            HttpUrlPolicy.ValidateStatic(parsed);
        }
        catch (HttpSecurityException)
        {
            return false;
        }

        if (!parsed.IsDefaultPort ||
            !string.IsNullOrEmpty(parsed.Query) ||
            !string.IsNullOrEmpty(parsed.Fragment) ||
            !string.Equals(parsed.Host, policy.AllowedHost, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        string candidateName = Path.GetFileName(parsed.AbsolutePath);
        if (!IsInstallerFileName(candidateName, policy) ||
            !SafeFileSystem.IsPathWithin(_cacheDir, Path.Combine(_cacheDir, candidateName), strict: false))
        {
            return false;
        }

        uri = parsed;
        fileName = candidateName;
        return true;
    }

    private async Task<string?> TryFindLatestIntactCacheAsync(InstallerPolicy policy, CancellationToken cancellationToken)
    {
        IReadOnlyList<FileSystemEntry> entries;
        try
        {
            entries = SafeFileSystem.ListBoundedDirectory(_cacheDir);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "掃描安裝器快取目錄失敗: {Path}", _cacheDir);
            return null;
        }

        var candidates = entries
            .Where(static entry => !entry.IsDirectory)
            .Select(entry => (entry.FullPath, Name: Path.GetFileName(entry.FullPath)))
            .Where(item => IsInstallerFileName(item.Name, policy))
            .Select(item => (item.FullPath, Version: item.Name[policy.Prefix.Length..^policy.Suffix.Length]))
            .OrderByDescending(static item => item.Version, Comparer<string>.Create(FlexVersion.Compare));

        foreach ((string fullPath, _) in candidates)
        {
            if (await IsCachedInstallerIntactAsync(fullPath, fullPath + ".sha256", cancellationToken).ConfigureAwait(false))
            {
                return fullPath;
            }
        }

        return null;
    }

    private void CleanupOldInstallers(LoaderKind loader, string currentJarPath)
    {
        if (!Policies.TryGetValue(loader, out var policy))
        {
            return;
        }

        try
        {
            string currentJarName = Path.GetFileName(currentJarPath);
            var groups = new Dictionary<string, (FileSystemEntry? Jar, List<(string Path, bool IsPart)> Artifacts)>(StringComparer.OrdinalIgnoreCase);

            foreach (FileSystemEntry entry in SafeFileSystem.ListBoundedDirectory(_cacheDir))
            {
                if (entry.IsDirectory)
                {
                    continue;
                }

                string fileName = Path.GetFileName(entry.FullPath);
                bool isPart = false;
                bool isJar = false;
                string jarName = fileName;
                if (fileName.EndsWith(".sha256", StringComparison.OrdinalIgnoreCase))
                {
                    jarName = fileName[..^".sha256".Length];
                }
                else if (fileName.EndsWith(".part", StringComparison.OrdinalIgnoreCase))
                {
                    jarName = fileName[..^".part".Length];
                    isPart = true;
                }
                else
                {
                    isJar = true;
                }

                if (!IsInstallerFileName(jarName, policy))
                {
                    continue;
                }

                if (!groups.TryGetValue(jarName, out var group))
                {
                    group = (null, []);
                }

                group.Artifacts.Add((entry.FullPath, isPart));
                groups[jarName] = (isJar ? entry : group.Jar, group.Artifacts);
            }

            var kept = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { currentJarName };
            int keepOther = Math.Max(0, policy.KeepCount - 1);
            if (keepOther > 0)
            {
                foreach (var (jarName, _) in groups
                    .Where(kv => !string.Equals(kv.Key, currentJarName, StringComparison.OrdinalIgnoreCase) && kv.Value.Jar is not null)
                    .OrderByDescending(static kv => kv.Value.Jar!.LastWriteTimeUtc)
                    .ThenByDescending(static kv => kv.Value.Jar!.CreationTimeUtc)
                    .ThenBy(static kv => kv.Key, StringComparer.OrdinalIgnoreCase)
                    .Take(keepOther))
                {
                    kept.Add(jarName);
                }
            }

            foreach (var (jarName, (_, artifacts)) in groups)
            {
                bool keepGroup = kept.Contains(jarName);
                foreach (var (path, isPart) in artifacts)
                {
                    if ((!keepGroup || isPart) && !SafeFileSystem.TryDeleteFile(path))
                    {
                        Logger.Warning("無法刪除舊版安裝器快取檔案: {Path}", path);
                    }
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清理 {Loader} 舊版安裝器快取時發生錯誤", loader);
        }
    }

    private static bool IsInstallerFileName(string name, InstallerPolicy policy) =>
        ModHelpers.IsJarFileName(name) &&
        name.StartsWith(policy.Prefix, StringComparison.OrdinalIgnoreCase) &&
        name.EndsWith(policy.Suffix, StringComparison.OrdinalIgnoreCase) &&
        name.Length > policy.Prefix.Length + policy.Suffix.Length;

    private sealed record InstallerPolicy(
        string Prefix,
        string Suffix,
        int KeepCount,
        Uri? MetaUri = null,
        string? AllowedHost = null,
        bool PreferStable = false,
        bool ReadMetaHashes = false);

    private sealed record InstallerDescriptor(Uri Uri, string FileName, string? ExpectedHash = null, string? HashAlgorithm = null);

    /// <summary>取得遠端雜湊檔內容；無檔、格式不符或連線失敗回傳 null</summary>
    private async Task<string?> TryFetchInstallerHashAsync(string hashUrl, int hexLength, CancellationToken cancellationToken)
    {
        try
        {
            return ExtractValidHexHash(await httpPort.GetTextAsync(new Uri(hashUrl), cancellationToken).ConfigureAwait(false), hexLength);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得安裝器雜湊檔失敗: {Url}", hashUrl);
            return null;
        }
    }

    private static async Task<bool> IsCachedInstallerIntactAsync(string jarPath, string hashSidecar, CancellationToken cancellationToken)
    {
        if (!SafeFileSystem.FileExists(jarPath) || !SafeFileSystem.FileExists(hashSidecar))
        {
            return false;
        }

        string recorded = (await SafeFileSystem.ReadAllTextAsync(hashSidecar, cancellationToken: cancellationToken).ConfigureAwait(false)).Trim();
        string actual = await HashCalculator.ComputeFileHashAsync(jarPath, cancellationToken: cancellationToken).ConfigureAwait(false);
        if (actual.Length > 0 && string.Equals(recorded, actual, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        Logger.Warning("快取安裝器雜湊不符，將重新下載: {Path}", jarPath);
        return false;
    }

    private static string? ExtractValidHexHash(string? text, int expectedLength)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        ReadOnlySpan<char> span = text.AsSpan().Trim();
        int separatorIdx = span.IndexOfAny(HashSeparators);
        ReadOnlySpan<char> firstToken = separatorIdx >= 0 ? span[..separatorIdx] : span;

        if (!HashCalculator.IsHexDigest(firstToken, expectedLength))
        {
            return null;
        }

        return firstToken.ToString();
    }

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

    private static (string? Url, string? Sha1) ExtractServerDownloadInfo(JsonDocument doc)
    {
        if (doc.RootElement.TryGetProperty("downloads", out var dl) &&
            dl.TryGetProperty("server", out var serverElem) &&
            serverElem.TryGetProperty("url", out var urlElem))
        {
            string? url = urlElem.GetString();
            string? sha1 = null;
            if (serverElem.TryGetProperty("sha1", out var sha1Elem))
            {
                sha1 = sha1Elem.GetString();
            }
            return (url, sha1);
        }
        return (null, null);
    }

    private sealed partial class InstallerProgressEstimator
    {
        private static readonly SearchValues<string> CompletionWords = SearchValues.Create(["successfully installed", "installation complete", "all done"], StringComparison.OrdinalIgnoreCase);
        private static readonly SearchValues<string> PatchingWords = SearchValues.Create(["patching", "remapping", "injecting"], StringComparison.OrdinalIgnoreCase);
        private static readonly SearchValues<string> ProcessingWords = SearchValues.Create(["processor", "processing", "applying"], StringComparison.OrdinalIgnoreCase);
        private static readonly SearchValues<string> DownloadingWords = SearchValues.Create(["downloading", "extracting", "task"], StringComparison.OrdinalIgnoreCase);

        private int _current = 30;

        internal int FeedOutput(string line)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                return _current;
            }

            // 百分比匹配
            var match = PercentRegex().Match(line);
            if (match.Success && int.TryParse(match.Groups[1].Value, out int pct))
            {
                _current = Math.Max(_current, Math.Min(95, pct));
                return _current;
            }

            ReadOnlySpan<char> text = line;
            if (text.ContainsAny(CompletionWords))
            {
                _current = 98;
            }
            else if (text.ContainsAny(PatchingWords))
            {
                _current = Math.Max(_current, 85);
            }
            else if (text.ContainsAny(ProcessingWords))
            {
                _current = Math.Max(_current, Math.Min(80, _current + 2));
            }
            else if (text.ContainsAny(DownloadingWords))
            {
                _current = Math.Max(_current, Math.Min(65, _current + 1));
            }
            else
            {
                // 持續輸出但未命中特定詞彙時微幅平穩推進
                _current = Math.Min(92, _current + 1);
            }

            return _current;
        }

        [GeneratedRegex(@"(?<!\d)(100|\d{1,2})(?:\.\d+)?\s*%")]
        private static partial Regex PercentRegex();
    }
}
