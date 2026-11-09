using MinecraftServerManager.Infrastructure.Logging;
using System.Buffers;
using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Core.Utilities;
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
    private readonly string _cacheDir = SafeFileSystem.ResolveStableDirectory(installerCacheDirectory, create: true);

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

        // 僅 Fabric 與 Quilt 安裝前需預先準備官方原版 server.jar（Forge 與 NeoForge 內建原版下載流程，無需此步驟）
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
        SafeReport("downloading", $"正在下載 {loader} 安裝器...", 38);
        string installerJarPath = await DownloadInstallerJarAsync(loader, minecraftVersion, loaderVersion, cancellationToken).ConfigureAwait(false);
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

            var exitResult = await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
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
                int pct = p.TotalBytes > 0 ? (int)(30 + ((double)p.BytesDownloaded / p.TotalBytes * 65)) : 30;
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
        CancellationToken cancellationToken)
    {
        string installerUrl = loader switch
        {
            LoaderKind.Fabric => "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.0.1/fabric-installer-1.0.1.jar",
            LoaderKind.Quilt => "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/0.11.0/quilt-installer-0.11.0.jar",
            LoaderKind.Forge => $"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraftVersion}-{loaderVersion}/forge-{minecraftVersion}-{loaderVersion}-installer.jar",
            LoaderKind.NeoForge => $"https://maven.neoforged.net/releases/net/neoforged/neoforge/{loaderVersion}/neoforge-{loaderVersion}-installer.jar",
            _ => throw new NotSupportedException($"不支援的 Loader: {loader}")
        };

        var uri = new Uri(installerUrl);
        string fileName = Path.GetFileName(uri.AbsolutePath);
        string destination = Path.Combine(_cacheDir, fileName);
        string hashSidecar = destination + ".sha256";

        // 快取安裝器執行前須與下載當下記錄之 SHA-256 相符，否則重新下載
        if (!await IsCachedInstallerIntactAsync(destination, hashSidecar, cancellationToken).ConfigureAwait(false))
        {
            string? expectedHash = null;
            string expectedAlgorithm = "sha256";

            try
            {
                string? sha256Text = await httpPort.GetTextAsync(new Uri(installerUrl + ".sha256"), cancellationToken).ConfigureAwait(false);
                string? hash256 = ExtractValidHexHash(sha256Text, 64);
                if (hash256 is not null)
                {
                    expectedHash = hash256;
                    expectedAlgorithm = "sha256";
                }
                else
                {
                    string? sha1Text = await httpPort.GetTextAsync(new Uri(installerUrl + ".sha1"), cancellationToken).ConfigureAwait(false);
                    string? hash1 = ExtractValidHexHash(sha1Text, 40);
                    if (hash1 is not null)
                    {
                        expectedHash = hash1;
                        expectedAlgorithm = "sha1";
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warning("遠端 Maven 若無校驗檔或網路異常，容許降級為一般下載: {0}", ex.Message);
            }

            var result = await httpPort.DownloadAsync(
                uri,
                destination,
                expectedHash: expectedHash,
                expectedHashAlgorithm: expectedAlgorithm,
                cancellationToken: cancellationToken).ConfigureAwait(false);
            if (!result.Success)
            {
                throw new InvalidOperationException($"下載 {loader} 安裝器失敗：{result.Error}");
            }

            await SafeFileSystem.WriteAllTextAsync(hashSidecar, await HashCalculator.Shared.ComputeFileHashAsync(destination, useCache: false, cancellationToken: cancellationToken).ConfigureAwait(false), cancellationToken: cancellationToken).ConfigureAwait(false);
        }

        return destination;
    }

    private static async Task<bool> IsCachedInstallerIntactAsync(string jarPath, string hashSidecar, CancellationToken cancellationToken)
    {
        if (!SafeFileSystem.FileExists(jarPath) || !SafeFileSystem.FileExists(hashSidecar))
        {
            return false;
        }

        string recorded = (await SafeFileSystem.ReadAllTextAsync(hashSidecar, cancellationToken: cancellationToken).ConfigureAwait(false)).Trim();
        string actual = await HashCalculator.Shared.ComputeFileHashAsync(jarPath, useCache: false, cancellationToken: cancellationToken).ConfigureAwait(false);
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
        private int _current = 30;

        public int FeedOutput(string line)
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

            if (line.Contains("successfully installed", StringComparison.OrdinalIgnoreCase) || line.Contains("installation complete", StringComparison.OrdinalIgnoreCase) || line.Contains("all done", StringComparison.OrdinalIgnoreCase))
            {
                _current = 98;
            }
            else if (line.Contains("patching", StringComparison.OrdinalIgnoreCase) || line.Contains("remapping", StringComparison.OrdinalIgnoreCase) || line.Contains("injecting", StringComparison.OrdinalIgnoreCase))
            {
                _current = Math.Max(_current, 85);
            }
            else if (line.Contains("processor", StringComparison.OrdinalIgnoreCase) || line.Contains("processing", StringComparison.OrdinalIgnoreCase) || line.Contains("applying", StringComparison.OrdinalIgnoreCase))
            {
                _current = Math.Max(_current, Math.Min(80, _current + 2));
            }
            else if (line.Contains("downloading", StringComparison.OrdinalIgnoreCase) || line.Contains("extracting", StringComparison.OrdinalIgnoreCase) || line.Contains("task", StringComparison.OrdinalIgnoreCase))
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
