using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed partial class ServerInspector : IServerInspector
{
    private static readonly (string Name, string Display, string[] Segments)[] SimpleLoaderLibraries =
    [
        ("fabric", "Fabric", ["net", "fabricmc", "fabric-loader"]),
        ("quilt", "Quilt", ["org", "quiltmc", "quilt-loader"]),
    ];

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInspector));
    private static readonly string[] ServerJarCandidates =
    [
        "run.bat",
        .. ServerLaunchTargetResolver.PreferredLaunchJars,
    ];

    private static readonly string[] MemoryCandidateScriptNames =
    [
        ServerDefaults.UserJvmArgsFileName,
        ServerDefaults.StartServerBatFileName,
        "start.bat",
        "run.bat",
        "launch.bat",
        "start.cmd",
        "run.cmd",
        "start.sh",
        "run.sh",
        "launch.sh",
    ];

    private static readonly string[] VersionJsonCandidateProperties = ["id", "name", "release_target"];

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
                MinecraftVersion = mcVersion,
                LoaderVersion = loaderVersion,
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

        // 搜尋其他 jar 檔案（paper*.jar 優先置前）
        foreach (string file in files)
        {
            if (ModHelpers.IsJarFileName(file) && !candidates.Contains(file))
            {
                if (file.StartsWith("paper", StringComparison.OrdinalIgnoreCase))
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
        var kind = (primary.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) || primary.StartsWith('@'))
            ? LaunchTargetKind.Script
            : LaunchTargetKind.Jar;

        string reason = primary.StartsWith('@')
            ? "偵測到 Forge / NeoForge 啟動引數檔"
            : primary.Equals("run.bat", StringComparison.OrdinalIgnoreCase)
                ? "偵測到官方推薦啟動腳本 run.bat"
                : primary.StartsWith("paper", StringComparison.OrdinalIgnoreCase)
                    ? "偵測到 PaperMC 官方伺服器核心"
                    : primary.StartsWith("fabric", StringComparison.OrdinalIgnoreCase)
                        ? "偵測到 Fabric 官方啟動程式"
                        : primary.Equals("server.jar", StringComparison.OrdinalIgnoreCase)
                            ? "標準 Minecraft 伺服器程式"
                            : "找到伺服器主程式";

        return new ServerLaunchTarget(
            kind: kind,
            value: primary,
            candidates: candidates,
            reason: reason);
    }

    private static (string LoaderType, string LoaderVersion, string MinecraftVersion, string LoaderTypeSource, string LoaderVersionSource, string MinecraftVersionSource) InspectLoaderAndVersion(
        string directory,
        HashSet<string> files,
        ServerLaunchTarget target)
    {
        var loaderType = new DetectedValue();
        var loaderVersion = new DetectedValue();
        var mcVersion = new DetectedValue();

        string librariesDir = Path.Combine(directory, "libraries");
        bool hasLibraries = SafeFileSystem.DirectoryExists(librariesDir);

        // 1. 檢查伺服器根目錄下的 version.json
        string? rootJsonMc = TryExtractMinecraftVersionFromRootJson(directory);
        if (!string.IsNullOrEmpty(rootJsonMc))
        {
            mcVersion.Set(rootJsonMc, "根目錄 version.json");
        }

        // 2. 檢查主程式 JAR 內部 metadata (version.json 與 MANIFEST.MF)
        if (!mcVersion.IsSet)
        {
            string? primaryJarPath = null;
            if (files.Contains("server.jar"))
            {
                primaryJarPath = Path.Combine(directory, "server.jar");
            }
            else if (!string.IsNullOrEmpty(target.Value) && ModHelpers.IsJarFileName(target.Value))
            {
                primaryJarPath = Path.Combine(directory, target.Value);
            }

            if (primaryJarPath is not null && SafeFileSystem.FileExists(primaryJarPath))
            {
                string? jarMc = TryExtractMinecraftVersionFromJar(primaryJarPath);
                if (!string.IsNullOrEmpty(jarMc))
                {
                    mcVersion.Set(jarMc, $"{Path.GetFileName(primaryJarPath)} 內部 metadata");
                }
            }
        }

        // 3. 檢查 libraries/ 結構以精確判定載入器與版本
        if (hasLibraries)
        {
            // NeoForge
            string neoLib = Path.Combine(librariesDir, "net", "neoforged", "neoforge");
            if (SafeFileSystem.DirectoryExists(neoLib))
            {
                loaderType.Set("neoforge", "libraries/net/neoforged/neoforge");
                try
                {
                    var subDirs = SafeFileSystem.ListBoundedDirectory(neoLib, maxEntries: 16, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
                        .Where(static e => e.IsDirectory)
                        .ToList();
                    if (subDirs.Count > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0].FullPath);
                        loaderVersion.Set(verName, $"libraries/net/neoforged/neoforge/{verName}");
                        string? derived = MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge(verName);
                        if (!string.IsNullOrEmpty(derived) && !mcVersion.IsSet)
                        {
                            mcVersion.Set(derived, $"從 NeoForge {verName} 推導");
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "探測 NeoForge 函式庫目錄失敗");
                }
            }

            // Forge
            string forgeLib = Path.Combine(librariesDir, "net", "minecraftforge", "forge");
            if (SafeFileSystem.DirectoryExists(forgeLib))
            {
                loaderType.Set("forge", "libraries/net/minecraftforge/forge");
                try
                {
                    var subDirs = SafeFileSystem.ListBoundedDirectory(forgeLib, maxEntries: 16, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
                        .Where(static e => e.IsDirectory);
                    foreach (var sub in subDirs)
                    {
                        string dirName = Path.GetFileName(sub.FullPath);
                        int dash = dirName.IndexOf('-');
                        if (dash > 0)
                        {
                            mcVersion.SetIfUnset(dirName[..dash], $"libraries/net/minecraftforge/forge/{dirName}");
                            loaderVersion.SetIfUnset(dirName[(dash + 1)..], $"libraries/net/minecraftforge/forge/{dirName}");
                            break;
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "探測 Forge 函式庫目錄失敗");
                }
            }

            // Fabric / Quilt：libraries 下的版本資料夾名稱即為載入器版本
            foreach (var (name, display, segments) in SimpleLoaderLibraries)
            {
                string libDir = Path.Combine([librariesDir, .. segments]);
                if (!SafeFileSystem.DirectoryExists(libDir))
                {
                    continue;
                }

                string relative = "libraries/" + string.Join('/', segments);
                loaderType.Set(name, relative);
                try
                {
                    var firstVersionDir = SafeFileSystem.ListBoundedDirectory(libDir, maxEntries: 16, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
                        .FirstOrDefault(static e => e.IsDirectory);
                    if (firstVersionDir is not null)
                    {
                        string verName = Path.GetFileName(firstVersionDir.FullPath);
                        loaderVersion.Set(verName, $"{relative}/{verName}");
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "探測 {Loader} 函式庫目錄失敗", display);
                }
            }
        }

        // 4. 從標準啟動檔名或特徵設定檔判斷載入器類型
        if (!loaderType.IsSet)
        {
            if (target.Value.StartsWith("paper", StringComparison.OrdinalIgnoreCase) ||
                files.Any(static f => f.StartsWith("paper-", StringComparison.OrdinalIgnoreCase) && ModHelpers.IsJarFileName(f)) ||
                files.Contains("paper-global.yml") || files.Contains("paper.yml") || files.Contains("paper-world-defaults.yml"))
            {
                loaderType.Set("paper", "Paper 伺服器特徵 (paper.jar 或 paper-global.yml)");
            }
            else if (files.Contains("fabric-server-launch.jar"))
            {
                loaderType.Set("fabric", "fabric-server-launch.jar 啟動檔名");
            }
            else if (files.Contains("quilt-server-launch.jar"))
            {
                loaderType.Set("quilt", "quilt-server-launch.jar 啟動檔名");
            }
            else if (target.Value.Equals("server.jar", StringComparison.OrdinalIgnoreCase) ||
                     target.Value.Equals("minecraft_server.jar", StringComparison.OrdinalIgnoreCase))
            {
                loaderType.Set("vanilla", "官方標準 server.jar 檔名");
            }
        }

        // 5. 從主程式檔名解析 (如 paper-1.21.4-165.jar 或 forge-1.20.1-47.2.0.jar)
        string exeName = target.Value;
        var paperMatch = PaperJarRegex().Match(exeName);
        if (paperMatch.Success)
        {
            mcVersion.SetIfUnset(paperMatch.Groups["mcVer"].Value, $"{exeName} 檔名");
            loaderVersion.SetIfUnset(paperMatch.Groups["build"].Value, $"{exeName} 檔名");
            loaderType.Set("paper", $"{exeName} 檔名");
        }

        var forgeMatch = ForgeJarRegex().Match(exeName);
        if (forgeMatch.Success)
        {
            mcVersion.SetIfUnset(forgeMatch.Groups[1].Value, $"{exeName} 檔名");
            loaderVersion.SetIfUnset(forgeMatch.Groups[2].Value, $"{exeName} 檔名");
            loaderType.SetIfUnset("forge", $"{exeName} 檔名");
        }
        else if (!mcVersion.IsSet)
        {
            string? extractedMc = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(exeName);
            if (!string.IsNullOrEmpty(extractedMc))
            {
                mcVersion.Set(extractedMc, $"{exeName} 檔名");
            }
        }

        // 6. 掃描 run.bat / win_args.txt 內容
        if (!mcVersion.IsSet || !loaderVersion.IsSet)
        {
            string runBat = Path.Combine(directory, "run.bat");
            string winArgs = Path.Combine(directory, "win_args.txt");
            string toCheck = SafeFileSystem.FileExists(runBat) ? runBat : (SafeFileSystem.FileExists(winArgs) ? winArgs : string.Empty);
            if (!string.IsNullOrEmpty(toCheck) && SafeFileSystem.GetFileLength(toCheck) <= MaxMetadataBytes)
            {
                try
                {
                    string content = SafeFileSystem.ReadAllText(toCheck);
                    var m = ForgeJarRegex().Match(content);
                    if (m.Success)
                    {
                        mcVersion.SetIfUnset(m.Groups[1].Value, $"{Path.GetFileName(toCheck)} 腳本內容");
                        loaderVersion.SetIfUnset(m.Groups[2].Value, $"{Path.GetFileName(toCheck)} 腳本內容");
                        loaderType.SetIfUnset("forge", $"{Path.GetFileName(toCheck)} 腳本內容");
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "檢查啟動腳本失敗");
                }
            }
        }

        // 7. 檢查 logs/latest.log 或最新修改之記錄檔
        if (!mcVersion.IsSet || !loaderVersion.IsSet)
        {
            string? logFile = FindLatestLogFile(directory);
            if (logFile is not null && SafeFileSystem.FileExists(logFile))
            {
                try
                {
                    using var sr = new StreamReader(SafeFileSystem.OpenRead(logFile), Encoding.UTF8);
                    int lineCount = 0;
                    string? line;
                    while ((line = sr.ReadLine()) is not null && lineCount++ < 2000)
                    {
                        if (!mcVersion.IsSet)
                        {
                            var mcMatch = McLogRegex().Match(line);
                            if (mcMatch.Success)
                            {
                                mcVersion.Set(mcMatch.Groups[1].Value, $"{Path.GetFileName(logFile)} 啟動記錄");
                            }
                        }

                        if (!loaderVersion.IsSet)
                        {
                            var forgeM = ForgeLogRegex().Match(line);
                            if (forgeM.Success)
                            {
                                loaderVersion.Set(forgeM.Groups[1].Value, $"{Path.GetFileName(logFile)} 載入器記錄");
                                loaderType.SetIfUnset("forge", $"{Path.GetFileName(logFile)} 載入器記錄");
                            }
                            else
                            {
                                var neoM = NeoForgeLogRegex().Match(line);
                                if (neoM.Success)
                                {
                                    loaderVersion.Set(neoM.Groups[1].Value, $"{Path.GetFileName(logFile)} 載入器記錄");
                                    loaderType.SetIfUnset("neoforge", $"{Path.GetFileName(logFile)} 載入器記錄");
                                }
                            }
                        }

                        if (mcVersion.IsSet && loaderVersion.IsSet)
                        {
                            break;
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "讀取伺服器記錄檔失敗");
                }
            }
        }

        if (string.Equals(loaderType.Value, "vanilla", StringComparison.OrdinalIgnoreCase)
            && string.IsNullOrWhiteSpace(loaderVersion.Value))
        {
            loaderVersion.Value = mcVersion.Value;
            loaderVersion.Source = mcVersion.Source;
        }

        return (loaderType.Value ?? "unknown", loaderVersion.Value ?? "unknown", mcVersion.Value ?? "unknown", loaderType.Source, loaderVersion.Source, mcVersion.Source);
    }

    /// <summary>偵測結果值與其來源說明（尚未偵測到時來源為「未偵測到」）</summary>
    private sealed class DetectedValue
    {
        public string? Value { get; set; }

        public string Source { get; set; } = "未偵測到";

        public bool IsSet => Value is not null;

        public void Set(string value, string source)
        {
            Value = value;
            Source = source;
        }

        public void SetIfUnset(string value, string source)
        {
            if (!IsSet)
            {
                Set(value, source);
            }
        }
    }

    private static string? FindLatestLogFile(string serverDirectory)
    {
        string logsDir = Path.Combine(serverDirectory, "logs");
        if (SafeFileSystem.DirectoryExists(logsDir))
        {
            string latestLog = Path.Combine(logsDir, "latest.log");
            if (SafeFileSystem.FileExists(latestLog))
            {
                return latestLog;
            }

            try
            {
                // 列舉結果已含最後寫入時間，不必對每個檔案再走一次路徑驗證
                string? newest = SafeFileSystem.ListBoundedDirectory(logsDir)
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

    private const long MaxMetadataBytes = 2L * 1024 * 1024;

    private static string? TryExtractMinecraftVersionFromRootJson(string directory)
    {
        string jsonPath = Path.Combine(directory, "version.json");
        if (!SafeFileSystem.FileExists(jsonPath))
        {
            return null;
        }

        try
        {
            byte[]? payload = SafeFileSystem.ReadRegularFile(jsonPath, MaxMetadataBytes);
            if (payload is null)
            {
                return null;
            }

            return ExtractMinecraftVersionFromVersionJson(payload);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            Logger.Warning(ex, "解析 version.json 失敗");
        }
        return null;
    }

    private static string? ExtractMinecraftVersionFromVersionJson(byte[] payload)
    {
        using var doc = JsonCodec.ParseDocument(payload);
        var root = doc.RootElement;
        foreach (string prop in VersionJsonCandidateProperties)
        {
            if (root.TryGetProperty(prop, out var val)
                && val.GetString() is { Length: > 0 } text
                && MinecraftVersionSemantics.ExtractMinecraftVersionFromText(text) is { Length: > 0 } extracted)
            {
                return extracted;
            }
        }

        return null;
    }

    private static string? TryExtractMinecraftVersionFromJar(string jarPath)
    {
        try
        {
            using var zip = SafeZipArchive.OpenRead(jarPath);
            var versionEntry = zip.GetEntry("version.json");
            if (versionEntry is not null && SafeZipArchive.ReadEntryBytesBounded(versionEntry, (int)MaxMetadataBytes) is { } versionBytes)
            {
                if (ExtractMinecraftVersionFromVersionJson(versionBytes) is { } fromJson)
                {
                    return fromJson;
                }
            }

            var manifestEntry = zip.GetEntry("META-INF/MANIFEST.MF");
            if (manifestEntry is not null && SafeZipArchive.ReadEntryTextBounded(manifestEntry, (int)MaxMetadataBytes) is { } manifestText)
            {
                string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(manifestText);
                if (!string.IsNullOrEmpty(extracted))
                {
                    return extracted;
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or JsonException)
        {
            Logger.Warning(ex, "解析 JAR 清單版本失敗");
        }
        return null;
    }

    private static (int? MaxMb, int? MinMb) TryExtractMemoryFromFile(string filePath)
    {
        if (!SafeFileSystem.FileExists(filePath) || SafeFileSystem.GetFileLength(filePath) > MaxMetadataBytes)
        {
            return (null, null);
        }

        try
        {
            int? foundMax = null;
            int? foundMin = null;

            using var stream = SafeFileSystem.OpenRead(filePath);
            using var reader = new StreamReader(stream);
            while (reader.ReadLine() is { } line)
            {
                string trimmed = line.Trim();
                if (trimmed.Length == 0 || trimmed.StartsWith('#') || trimmed.StartsWith("rem ", StringComparison.OrdinalIgnoreCase) || trimmed.StartsWith("::", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                int? xmx = MemoryUtils.ParseMemorySetting(trimmed, "Xmx");
                if (xmx.HasValue)
                {
                    foundMax = xmx.Value;
                }

                int? xms = MemoryUtils.ParseMemorySetting(trimmed, "Xms");
                if (xms.HasValue)
                {
                    foundMin = xms.Value;
                }
            }

            return (foundMax, foundMin);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "讀取檔案記憶體設定失敗 ({Path})", filePath);
            return (null, null);
        }
    }

    private static (int MaxMb, int? MinMb) InspectMemory(string directory)
    {
        int maxMb = ServerDefaults.DefaultMemoryMaxMb;
        int? minMb = null;
        bool found = false;

        foreach (string candidate in MemoryCandidateScriptNames)
        {
            string candidatePath = Path.Combine(directory, candidate);
            var (parsedMax, parsedMin) = TryExtractMemoryFromFile(candidatePath);
            if (parsedMax.HasValue)
            {
                maxMb = parsedMax.Value;
                minMb = parsedMin;
                found = true;
                Logger.Information("從來源檔案「{File}」解析到記憶體設定: Max={Max}MB, Min={Min}MB", candidate, maxMb, minMb);
                break;
            }
        }

        if (!found)
        {
            try
            {
                foreach (string subDir in SafeFileSystem.EnumerateDirectories(directory))
                {
                    foreach (string candidate in MemoryCandidateScriptNames)
                    {
                        string candidatePath = Path.Combine(subDir, candidate);
                        var (parsedMax, parsedMin) = TryExtractMemoryFromFile(candidatePath);
                        if (parsedMax.HasValue)
                        {
                            maxMb = parsedMax.Value;
                            minMb = parsedMin;
                            found = true;
                            Logger.Information("從子目錄檔案「{File}」解析到記憶體設定: Max={Max}MB, Min={Min}MB", Path.GetRelativePath(directory, candidatePath), maxMb, minMb);
                            break;
                        }
                    }

                    if (found)
                    {
                        break;
                    }
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning(ex, "掃描子目錄記憶體設定失敗");
            }
        }

        return (maxMb, minMb);
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
