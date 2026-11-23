using System.Collections.Frozen;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed partial class ServerInspector : IServerInspector
{
    /// <summary>可由 libraries 目錄直接判定的載入器（依序偵測，後者覆寫前者）</summary>
    private static readonly LoaderKind[] DetectableLibraryLoaders = [LoaderKind.NeoForge, LoaderKind.Forge, LoaderKind.Fabric, LoaderKind.Quilt];

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInspector));
    private static readonly string[] ServerJarCandidates =
    [
        ServerDefaults.RunBatFileName,
        .. ServerLaunchTargetResolver.PreferredLaunchJars,
    ];

    private static readonly string[] VersionJsonCandidateProperties = ["id", "name", "release_target"];

    private static readonly string[] ManifestVersionKeys = ["Implementation-Version", "Specification-Version"];

    private static readonly FrozenSet<string> NonScriptDirectories = FrozenSet.Create(
        StringComparer.OrdinalIgnoreCase,
        "world", "world_nether", "world_the_end", ServerDefaults.LogsDirectoryName, ServerDefaults.CrashReportsDirectoryName, ServerDefaults.LibrariesDirectoryName, ServerDefaults.ModsDirectoryName, "config",
        "plugins", ServerDefaults.BackupsDirectoryName, "cache", "versions", "defaultconfigs", "kubejs");

    /// <summary>於背景執行緒讀取伺服器根目錄少量檔案完成偵測（不走訪世界資料）</summary>
    public Task<ServerInspection> InspectAsync(
        string serverDirectory,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => Inspect(serverDirectory), cancellationToken);

    private static ServerInspection Inspect(string serverDirectory)
    {
        try
        {
            string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
            if (!SafeFileSystem.DirectoryExists(stableDir))
            {
                Logger.Warning("伺服器偵測失敗，找不到目錄: {Path}", serverDirectory);
                return new ServerInspection { Path = serverDirectory };
            }

            var entries = SafeFileSystem.ListBoundedDirectory(stableDir, maxEntries: 512, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false);
            var files = entries.Where(static e => !e.IsDirectory).Select(static e => Path.GetFileName(e.FullPath)).ToHashSet(StringComparer.OrdinalIgnoreCase);

            var launchTarget = InspectLaunchTarget(stableDir, files);
            var (loaderType, loaderVersion, mcVersion, loaderTypeSource, loaderVersionSource, mcVersionSource) =
                InspectLoaderAndVersion(stableDir, files, launchTarget);
            var (maxMb, minMb) = InspectMemory(stableDir);

            Logger.Information(
                "伺服器「{Path}」偵測結果: Minecraft版本={McVersion} (來源: {McSource}), 載入器={LoaderType} (來源: {LoaderSource}), 載入器版本={LoaderVersion} (來源: {LoaderVerSource})",
                stableDir,
                mcVersion,
                mcVersionSource,
                loaderType,
                loaderTypeSource,
                loaderVersion,
                loaderVersionSource);

            return new ServerInspection
            {
                Path = stableDir,
                IsCandidate = launchTarget.Kind != LaunchTargetKind.None || files.Contains(ServerDefaults.ServerPropertiesFileName),
                LoaderType = loaderType,
                MinecraftVersion = Domain.ValueObjects.MinecraftVersion.TryParse(mcVersion, out var parsedVersion) ? parsedVersion : null,
                LoaderVersion = string.IsNullOrWhiteSpace(loaderVersion) ? null : loaderVersion,
                LaunchTarget = launchTarget,
                MemoryMaxMb = maxMb,
                MemoryMinMb = minMb,
            };
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "伺服器偵測發生例外: {Path}", serverDirectory);
            return new ServerInspection { Path = serverDirectory };
        }
    }

    private static ServerLaunchTarget InspectLaunchTarget(string directory, HashSet<string> files)
    {
        var candidates = new List<string>();

        // 搜尋標準目標
        foreach (string preferred in ServerJarCandidates)
        {
            if (files.Contains(preferred))
            {
                candidates.Add(preferred);
            }
        }

        // 檢查 Forge / NeoForge libraries 中的 win_args.txt
        string? libWinArgs = ServerLaunchTargetResolver.FindLibraryWinArgs(directory);
        if (libWinArgs is not null && !candidates.Contains(libWinArgs))
        {
            candidates.Insert(0, libWinArgs);
        }

        // 搜尋其他 jar 檔案（paper*.jar 優先置前，排除 *-installer.jar）
        foreach (string file in files)
        {
            if (ModHelpers.IsJarFileName(file)
                && !file.Contains("installer", StringComparison.OrdinalIgnoreCase)
                && !candidates.Contains(file))
            {
                if (LoaderLayout.IsPaperJarName(file))
                {
                    candidates.Insert(0, file);
                }
                else
                {
                    candidates.Add(file);
                }
            }
        }

        if (candidates.Count == 0)
        {
            return ServerLaunchTarget.None();
        }

        string primary = candidates[0];
        var kind = (primary.EndsWith(ServerDefaults.BatchScriptExtension, StringComparison.OrdinalIgnoreCase) || primary.StartsWith('@'))
            ? LaunchTargetKind.Script
            : LaunchTargetKind.Jar;

        string reason = primary.StartsWith('@')
            ? "偵測到 Forge / NeoForge 啟動引數檔"
            : primary.Equals(ServerDefaults.RunBatFileName, StringComparison.OrdinalIgnoreCase)
                ? "偵測到官方推薦啟動腳本 run.bat"
                : LoaderLayout.IsPaperJarName(primary)
                    ? "偵測到 PaperMC 官方伺服器核心"
                    : primary.StartsWith("fabric", StringComparison.OrdinalIgnoreCase)
                        ? "偵測到 Fabric 官方啟動程式"
                        : primary.Equals(ServerDefaults.ServerJarFileName, StringComparison.OrdinalIgnoreCase)
                            ? "標準 Minecraft 伺服器程式"
                            : "找到伺服器主程式";

        return new ServerLaunchTarget(
            kind: kind,
            value: primary,
            candidates: candidates,
            reason: reason);
    }

    private static (LoaderKind LoaderType, string? LoaderVersion, string? MinecraftVersion, string LoaderTypeSource, string LoaderVersionSource, string MinecraftVersionSource) InspectLoaderAndVersion(
        string directory,
        HashSet<string> files,
        ServerLaunchTarget target)
    {
        var loaderType = new DetectedValue<LoaderKind>();
        var loaderVersion = new DetectedValue<string>();
        var mcVersion = new DetectedValue<string>();

        // 1 & 2. 根目錄 version.json 與主程式 JAR 內部 metadata
        DetectMinecraftVersionFromMetadata(directory, files, target, mcVersion);

        // 3. libraries/ 結構偵測（NeoForge / Forge / Fabric / Quilt）
        DetectLoaderFromLibraries(directory, loaderType, loaderVersion, mcVersion);

        // 4. 標準啟動檔名與特徵設定檔
        DetectLoaderFromMarkers(files, target, loaderType);

        // 5. 主程式檔名解析 (paper / forge / 一般版本文字)
        DetectFromLaunchTargetFileName(target, loaderType, loaderVersion, mcVersion);

        // 6. 掃描 run.bat / win_args.txt 內容
        if (!mcVersion.IsSet || !loaderVersion.IsSet)
        {
            DetectFromLaunchScripts(directory, loaderType, loaderVersion, mcVersion);
        }

        // 7. 檢查 logs/latest.log 或最新修改之記錄檔
        if (!mcVersion.IsSet || !loaderVersion.IsSet)
        {
            DetectFromLogs(directory, loaderType, loaderVersion, mcVersion);
        }

        if (loaderType.Value == LoaderKind.Vanilla && string.IsNullOrWhiteSpace(loaderVersion.Value))
        {
            loaderVersion.Value = mcVersion.Value;
            loaderVersion.Source = mcVersion.Source;
        }

        return (loaderType.Value, loaderVersion.Value, mcVersion.Value, loaderType.Source, loaderVersion.Source, mcVersion.Source);
    }

    private static string? FindLatestLogFile(string serverDirectory)
    {
        string logsDir = Path.Combine(serverDirectory, ServerDefaults.LogsDirectoryName);
        if (SafeFileSystem.DirectoryExists(logsDir))
        {
            string latestLog = Path.Combine(logsDir, ServerDefaults.LatestLogFileName);
            if (SafeFileSystem.FileExists(latestLog))
            {
                return latestLog;
            }

            try
            {
                // 列舉結果已含最後寫入時間，不必對每個檔案再走一次路徑驗證
                string? newest = SafeFileSystem.ListBoundedDirectory(logsDir, rejectReparse: false)
                    .Where(static e => !e.IsDirectory && e.FullPath.EndsWith(".log", StringComparison.OrdinalIgnoreCase))
                    .OrderByDescending(static e => e.LastWriteTimeUtc)
                    .Select(static e => e.FullPath)
                    .FirstOrDefault();
                if (newest is not null)
                {
                    return newest;
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning(ex, "尋找最新記錄檔失敗");
            }
        }

        string rootLog = Path.Combine(serverDirectory, "server.log");
        return SafeFileSystem.FileExists(rootLog) ? rootLog : null;
    }

    [GeneratedRegex(@"forge[-_](\d+\.\d+(?:\.\d+)?)[-_](\d+\.\d+(?:\.\d+)?).*\.jar", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex ForgeJarRegex();

    [GeneratedRegex(@"(?:Starting minecraft server version|Server version:|Minecraft)\s+(\d+\.\d+(?:\.\d+)?)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex McLogRegex();

    [GeneratedRegex(@"(?:fml\.forgeVersion,\s*|MinecraftForge v|Forge\s+)(\d+\.\d+\.\d+)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex ForgeLogRegex();

    [GeneratedRegex(@"^paper-(?<mcVer>\d+\.\d+(?:\.\d+)?)-(?<build>\d+)\.jar$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex PaperJarRegex();

    [GeneratedRegex(@"NeoForge\s+(?:version\s+|v)?(\d+\.\d+\.\d+)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex NeoForgeLogRegex();
}
