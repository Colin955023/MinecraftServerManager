using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderInstallerService(
    IHttpPort httpPort,
    IProcessRunner processRunner,
    string installerCacheDirectory) : ILoaderInstallerService
{
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

        // 僅 Fabric 與 Quilt 安裝前需預先準備官方原版 server.jar（Forge 與 NeoForge 內建原版下載流程，無需此步驟）
        if (loader is LoaderKind.Fabric or LoaderKind.Quilt)
        {
            progress?.Report(new LoaderInstallProgress("vanilla_prepare", "正在準備原版伺服器檔案...", 5));
            string serverJarPath = Path.Combine(stableServerDir, "server.jar");
            if (!File.Exists(serverJarPath))
            {
                await EnsureVanillaServerJarAsync(minecraftVersion, stableServerDir, progress, cancellationToken).ConfigureAwait(false);
            }
        }

        // 下載各 Loader Installer
        progress?.Report(new LoaderInstallProgress("downloading", $"正在下載 {loader} 安裝器...", 10));
        string installerJarPath = await DownloadInstallerJarAsync(loader, minecraftVersion, loaderVersion, cancellationToken).ConfigureAwait(false);

        // 組合啟動參數
        progress?.Report(new LoaderInstallProgress("installing", $"正在執行 {loader} 伺服器安裝...", 30));
        var spec = BuildProcessStartSpec(loader, minecraftVersion, loaderVersion, installerJarPath, stableServerDir, javaExecutablePath);

        // 執行安裝程序
        var process = await processRunner.StartAsync(spec, cancellationToken).ConfigureAwait(false);
        await using (process.ConfigureAwait(false))
        {
            var tracker = new InstallerProgressEstimator();
            process.OutputReceived += output =>
            {
                int estimated = tracker.FeedOutput(output.Text);
                progress?.Report(new LoaderInstallProgress("installing", output.Text, estimated));
            };

            var exitResult = await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            if (exitResult.ExitCode != 0)
            {
                throw new InvalidOperationException($"{loader} 安裝失敗，處理序結束代碼：{exitResult.ExitCode}");
            }
        }

        // 探索主要啟動檔案
        progress?.Report(new LoaderInstallProgress("finalizing", "正在確認伺服器啟動檔案...", 95));
        string launchTarget = ResolveLaunchTarget(stableServerDir, loader);

        progress?.Report(new LoaderInstallProgress("completed", "安裝完成", 100));
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

        string buildEndpoint = string.IsNullOrWhiteSpace(loaderVersion) || loaderVersion.Contains("最新", StringComparison.OrdinalIgnoreCase) || loaderVersion.Equals("latest", StringComparison.OrdinalIgnoreCase)
            ? $"https://fill.papermc.io/v3/projects/paper/versions/{minecraftVersion}/builds/latest"
            : $"https://fill.papermc.io/v3/projects/paper/versions/{minecraftVersion}/builds/{loaderVersion.Trim()}";

        string? buildJson = await httpPort.GetTextAsync(new Uri(buildEndpoint), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(buildJson))
        {
            throw new InvalidOperationException($"無法取得 PaperMC {minecraftVersion} 的建置下載資訊");
        }

        var (downloadUrl, fileName, sha256) = ExtractPaperDownloadInfo(buildJson);
        if (string.IsNullOrEmpty(downloadUrl))
        {
            throw new InvalidOperationException($"找不到 PaperMC {minecraftVersion} 的伺服器下載連結");
        }

        string targetJarName = !string.IsNullOrWhiteSpace(fileName) ? fileName : "paper.jar";
        string targetJarPath = Path.Combine(serverDirectory, targetJarName);

        progress?.Report(new LoaderInstallProgress("downloading", $"正在下載 {targetJarName}...", 20));

        var downloadResult = await httpPort.DownloadAsync(
            new Uri(downloadUrl),
            targetJarPath,
            new Progress<HttpProgress>(p =>
            {
                int pct = p.TotalBytes > 0 ? (int)(20 + ((double)p.BytesDownloaded / p.TotalBytes * 75)) : 20;
                progress?.Report(new LoaderInstallProgress("downloading", $"正在下載 {targetJarName} ({p.BytesDownloaded / 1024 / 1024} MB)...", pct));
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
        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("downloads", out var downloadsProp) || downloadsProp.ValueKind != JsonValueKind.Object)
        {
            return (null, null, null);
        }

        JsonElement item;
        if (downloadsProp.TryGetProperty("server:application", out var appProp))
        {
            item = appProp;
        }
        else
        {
            item = downloadsProp.EnumerateObject().FirstOrDefault().Value;
        }

        if (item.ValueKind != JsonValueKind.Object)
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
        string? manifestJson = await httpPort.GetTextAsync(new Uri("https://piston-meta.mojang.com/mc/game/version_manifest.json"), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(manifestJson))
        {
            throw new InvalidOperationException("無法取得 Minecraft 官方版本清單");
        }

        string? versionMetaUrl = ExtractVersionMetaUrl(manifestJson, minecraftVersion);
        if (string.IsNullOrEmpty(versionMetaUrl))
        {
            throw new InvalidOperationException($"找不到 Minecraft {minecraftVersion} 的官方下載詮釋資料");
        }

        string? metaJson = await httpPort.GetTextAsync(new Uri(versionMetaUrl), cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(metaJson))
        {
            throw new InvalidOperationException($"無法取得 Minecraft {minecraftVersion} 的版本詮釋資料");
        }

        var (serverDownloadUrl, expectedSha1) = ExtractServerDownloadInfo(metaJson);
        if (string.IsNullOrEmpty(serverDownloadUrl))
        {
            throw new InvalidOperationException($"找不到 Minecraft {minecraftVersion} 的 server.jar 下載連結");
        }

        string targetJar = Path.Combine(serverDirectory, "server.jar");
        progress?.Report(new LoaderInstallProgress("downloading", "正在下載原版 server.jar...", 30));

        var downloadResult = await httpPort.DownloadAsync(
            new Uri(serverDownloadUrl),
            targetJar,
            new Progress<HttpProgress>(p =>
            {
                int pct = p.TotalBytes > 0 ? (int)(30 + ((double)p.BytesDownloaded / p.TotalBytes * 65)) : 30;
                progress?.Report(new LoaderInstallProgress("downloading", $"正在下載原版 server.jar ({p.BytesDownloaded / 1024 / 1024} MB)...", pct));
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

        if (!File.Exists(destination))
        {
            var result = await httpPort.DownloadAsync(uri, destination, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (!result.Success)
            {
                throw new InvalidOperationException($"下載 {loader} 安裝器失敗：{result.Error}");
            }
        }

        return destination;
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
                if (!string.IsNullOrWhiteSpace(loaderVersion))
                {
                    args.AddRange(["server", "-mcversion", minecraftVersion, "-loader", loaderVersion, "-dir", serverDirectory]);
                }
                else
                {
                    args.AddRange(["server", "-mcversion", minecraftVersion, "-dir", serverDirectory]);
                }
                break;
            case LoaderKind.Quilt:
                if (!string.IsNullOrWhiteSpace(loaderVersion))
                {
                    args.AddRange(["install", "server", minecraftVersion, loaderVersion, $"--install-dir={serverDirectory}"]);
                }
                else
                {
                    args.AddRange(["install", "server", minecraftVersion, $"--install-dir={serverDirectory}"]);
                }
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

    private static string ResolveLaunchTarget(string serverDirectory, LoaderKind loader)
    {
        // 優先從 Forge / NeoForge 的 run.bat 提取 @...win_args.txt
        string runBat = Path.Combine(serverDirectory, "run.bat");
        if (File.Exists(runBat))
        {
            try
            {
                string runBatContent = File.ReadAllText(runBat);
                var match = WinArgsRegex().Match(runBatContent);
                if (match.Success)
                {
                    string matchedArgs = match.Groups[1].Value.Trim().Trim('"').Replace('\\', '/');
                    return "@" + matchedArgs;
                }
            }
            catch
            {
            }
        }

        // 檢查 Forge / NeoForge libraries 中的 win_args.txt
        string forgeLib = Path.Combine(serverDirectory, "libraries", "net", "minecraftforge", "forge");
        if (Directory.Exists(forgeLib))
        {
            foreach (string sub in Directory.GetDirectories(forgeLib))
            {
                string winArgs = Path.Combine(sub, "win_args.txt");
                if (File.Exists(winArgs))
                {
                    return "@" + Path.GetRelativePath(serverDirectory, winArgs).Replace('\\', '/');
                }
            }
        }

        string neoLib = Path.Combine(serverDirectory, "libraries", "net", "neoforged", "neoforge");
        if (Directory.Exists(neoLib))
        {
            foreach (string sub in Directory.GetDirectories(neoLib))
            {
                string winArgs = Path.Combine(sub, "win_args.txt");
                if (File.Exists(winArgs))
                {
                    return "@" + Path.GetRelativePath(serverDirectory, winArgs).Replace('\\', '/');
                }
            }
        }

        var files = SafeFileSystem.ListBoundedDirectory(serverDirectory, rejectReparse: false)
            .Where(e => !e.IsDirectory && e.FullPath.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
            .Select(e => Path.GetFileName(e.FullPath))
            .ToList();

        string? preferred = loader switch
        {
            LoaderKind.Paper => files.FirstOrDefault(f => f.StartsWith("paper", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.Fabric => files.FirstOrDefault(f => f.StartsWith("fabric-server-launch", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.Quilt => files.FirstOrDefault(f => f.StartsWith("quilt-server-launch", StringComparison.OrdinalIgnoreCase)),
            LoaderKind.Forge => files.FirstOrDefault(f => f.StartsWith("forge", StringComparison.OrdinalIgnoreCase) && !f.Contains("installer")),
            LoaderKind.NeoForge => files.FirstOrDefault(f => f.StartsWith("neoforge", StringComparison.OrdinalIgnoreCase) && !f.Contains("installer")),
            _ => null
        };

        if (preferred is not null)
        {
            return preferred;
        }

        if (File.Exists(runBat))
        {
            return "run.bat";
        }

        return files.FirstOrDefault(f => f.Equals("server.jar", StringComparison.OrdinalIgnoreCase)) ?? "server.jar";
    }

    [GeneratedRegex(@"(?i)@([^\s""]+win_args\.txt)")]
    private static partial Regex WinArgsRegex();

    private static string? ExtractVersionMetaUrl(string manifestJson, string targetVersion)
    {
        using var doc = JsonDocument.Parse(manifestJson);
        if (doc.RootElement.TryGetProperty("versions", out var versionsElem))
        {
            foreach (var elem in versionsElem.EnumerateArray())
            {
                if (elem.GetProperty("id").GetString() == targetVersion &&
                    elem.TryGetProperty("url", out var urlElem))
                {
                    return urlElem.GetString();
                }
            }
        }
        return null;
    }

    private static (string? Url, string? Sha1) ExtractServerDownloadInfo(string metaJson)
    {
        using var doc = JsonDocument.Parse(metaJson);
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

            string lower = line.ToLowerInvariant();
            if (lower.Contains("successfully installed") || lower.Contains("installation complete"))
            {
                _current = 95;
            }
            else if (lower.Contains("patching") || lower.Contains("remapping"))
            {
                _current = Math.Max(_current, 85);
            }
            else if (lower.Contains("downloading") || lower.Contains("processor"))
            {
                _current = Math.Min(80, _current + 1);
            }

            return _current;
        }

        [GeneratedRegex(@"(?<!\d)(100|\d{1,2})(?:\.\d+)?\s*%")]
        private static partial Regex PercentRegex();
    }
}
