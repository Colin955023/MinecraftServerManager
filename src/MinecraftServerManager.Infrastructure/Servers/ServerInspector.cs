using System.IO.Compression;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed partial class ServerInspector : IServerInspector
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerInspector");

    private static readonly string[] ServerJarCandidates =
    [
        "run.bat",
        "fabric-server-launch.jar",
        "quilt-server-launch.jar",
        "server.jar",
        "minecraft_server.jar",
    ];

    public Task<ServerInspection> InspectAsync(
        string serverDirectory,
        ServerInspectionIntent? intent = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        try
        {
            string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
            if (!Directory.Exists(stableDir))
            {
                return Task.FromResult(new ServerInspection(
                    path: serverDirectory,
                    revision: string.Empty,
                    isCandidate: false,
                    error: "找不到伺服器目錄"));
            }

            var entries = SafeFileSystem.ListBoundedDirectory(stableDir, maxEntries: 512, maxTotalBytes: 10 * 1024 * 1024, rejectReparse: false);
            var files = entries.Where(e => !e.IsDirectory).Select(e => Path.GetFileName(e.FullPath)).ToHashSet(StringComparer.OrdinalIgnoreCase);

            var eulaState = InspectEula(stableDir, files);
            var launchTarget = InspectLaunchTarget(files);
            var (loaderType, loaderVersion, mcVersion, loaderTypeSource, loaderVersionSource, mcVersionSource) =
                InspectLoaderAndVersion(stableDir, files, launchTarget);
            var (maxMb, minMb) = InspectMemory(stableDir);
            long totalSizeBytes = CalculateDirectorySize(stableDir);

            bool isCandidate = launchTarget.Kind != LaunchTargetKind.None || files.Contains("server.properties");
            bool launchable = launchTarget.Kind != LaunchTargetKind.None && eulaState == EulaState.Accepted;
            bool statusReady = launchable && !string.IsNullOrEmpty(mcVersion) && mcVersion != "unknown";

            var revisionBuilder = new StringBuilder();
            foreach (string? file in files.OrderBy(f => f, StringComparer.OrdinalIgnoreCase))
            {
                revisionBuilder.Append(file).Append(';');
            }
            string revision = HashCalculator.ComputeSha256(revisionBuilder.ToString());

            var evidence = new Dictionary<string, string>
            {
                ["EulaState"] = eulaState.ToString(),
                ["LaunchTarget"] = launchTarget.Value,
                ["Loader"] = loaderType,
                ["MinecraftVersion"] = mcVersion,
                ["LoaderVersion"] = loaderVersion,
                ["LoaderTypeSource"] = loaderTypeSource,
                ["LoaderVersionSource"] = loaderVersionSource,
                ["MinecraftVersionSource"] = mcVersionSource,
            };

            Logger.Information(
                "伺服器「{Path}」偵測結果: Minecraft版本={McVersion} (來源: {McSource}), 載入器={LoaderType} (來源: {LoaderSource}), 載入器版本={LoaderVersion} (來源: {LoaderVerSource})",
                stableDir,
                mcVersion,
                mcVersionSource,
                loaderType,
                loaderTypeSource,
                loaderVersion,
                loaderVersionSource);

            return Task.FromResult(new ServerInspection(
                path: stableDir,
                revision: revision,
                isCandidate: isCandidate,
                error: string.Empty,
                loaderType: loaderType,
                minecraftVersion: mcVersion,
                loaderVersion: loaderVersion,
                evidence: evidence,
                launchTarget: launchTarget,
                memoryMaxMb: maxMb,
                memoryMinMb: minMb,
                eulaState: eulaState,
                statusReady: statusReady,
                launchable: launchable,
                totalSizeBytes: totalSizeBytes));
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "伺服器偵測發生例外: {Path}, 原因: {Message}", serverDirectory, ex.Message);
            return Task.FromResult(new ServerInspection(
                path: serverDirectory,
                revision: string.Empty,
                isCandidate: false,
                error: ex.Message));
        }
    }

    private static long CalculateDirectorySize(string directory)
    {
        long totalBytes = 0L;
        try
        {
            var dirInfo = new DirectoryInfo(directory);
            if (!dirInfo.Exists)
            {
                return 0L;
            }

            foreach (var file in dirInfo.EnumerateFiles("*", new EnumerationOptions
            {
                RecurseSubdirectories = true,
                IgnoreInaccessible = true,
                AttributesToSkip = FileAttributes.ReparsePoint
            }))
            {
                totalBytes += file.Length;
            }
        }
        catch
        {
        }
        return totalBytes;
    }

    private static EulaState InspectEula(string directory, HashSet<string> files)
    {
        if (!files.Contains("eula.txt"))
        {
            return EulaState.Missing;
        }

        try
        {
            string path = Path.Combine(directory, "eula.txt");
            string content = File.ReadAllText(path, Encoding.UTF8);
            if (content.Contains("eula=true", StringComparison.OrdinalIgnoreCase))
            {
                return EulaState.Accepted;
            }

            if (content.Contains("eula=false", StringComparison.OrdinalIgnoreCase))
            {
                return EulaState.Rejected;
            }

            return EulaState.Missing;
        }
        catch
        {
            return EulaState.Missing;
        }
    }

    private static ServerLaunchTarget InspectLaunchTarget(HashSet<string> files)
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

        // 搜尋其他 jar 檔案
        foreach (string file in files)
        {
            if (file.EndsWith(".jar", StringComparison.OrdinalIgnoreCase) && !candidates.Contains(file))
            {
                candidates.Add(file);
            }
        }

        if (candidates.Count == 0)
        {
            return ServerLaunchTarget.None();
        }

        string primary = candidates[0];
        var kind = primary.EndsWith(".bat", StringComparison.OrdinalIgnoreCase)
            ? LaunchTargetKind.Script
            : LaunchTargetKind.Jar;

        string reason = primary.Equals("run.bat", StringComparison.OrdinalIgnoreCase)
            ? "偵測到官方推薦啟動腳本 run.bat"
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
        string loaderType = "unknown";
        string loaderVersion = "unknown";
        string mcVersion = "unknown";
        string loaderTypeSource = "未偵測到";
        string loaderVersionSource = "未偵測到";
        string mcVersionSource = "未偵測到";

        string librariesDir = Path.Combine(directory, "libraries");
        bool hasLibraries = Directory.Exists(librariesDir);

        // 1. 檢查伺服器根目錄下的 version.json
        string? rootJsonMc = TryExtractMinecraftVersionFromRootJson(directory);
        if (!string.IsNullOrEmpty(rootJsonMc))
        {
            mcVersion = rootJsonMc;
            mcVersionSource = "根目錄 version.json";
        }

        // 2. 檢查主程式 JAR 內部 metadata (version.json 與 MANIFEST.MF)
        if (mcVersion == "unknown")
        {
            string? primaryJarPath = null;
            if (files.Contains("server.jar"))
            {
                primaryJarPath = Path.Combine(directory, "server.jar");
            }
            else if (!string.IsNullOrEmpty(target.Value) && target.Value.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
            {
                primaryJarPath = Path.Combine(directory, target.Value);
            }

            if (primaryJarPath is not null && File.Exists(primaryJarPath))
            {
                string? jarMc = TryExtractMinecraftVersionFromJar(primaryJarPath);
                if (!string.IsNullOrEmpty(jarMc))
                {
                    mcVersion = jarMc;
                    mcVersionSource = $"{Path.GetFileName(primaryJarPath)} 內部 metadata";
                }
            }
        }

        // 3. 檢查 libraries/ 結構以精確判定載入器與版本
        if (hasLibraries)
        {
            // NeoForge
            string neoLib = Path.Combine(librariesDir, "net", "neoforged", "neoforge");
            if (Directory.Exists(neoLib))
            {
                loaderType = "neoforge";
                loaderTypeSource = "libraries/net/neoforged/neoforge";
                try
                {
                    string[] subDirs = Directory.GetDirectories(neoLib);
                    if (subDirs.Length > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0]);
                        loaderVersion = verName;
                        loaderVersionSource = $"libraries/net/neoforged/neoforge/{verName}";
                        string? derived = DeriveMinecraftVersionFromNeoForge(verName);
                        if (!string.IsNullOrEmpty(derived) && mcVersion == "unknown")
                        {
                            mcVersion = derived;
                            mcVersionSource = $"從 NeoForge {verName} 推導";
                        }
                    }
                }
                catch { }
            }

            // Forge
            string forgeLib = Path.Combine(librariesDir, "net", "minecraftforge", "forge");
            if (Directory.Exists(forgeLib))
            {
                loaderType = "forge";
                loaderTypeSource = "libraries/net/minecraftforge/forge";
                try
                {
                    foreach (string sub in Directory.GetDirectories(forgeLib))
                    {
                        string dirName = Path.GetFileName(sub);
                        int dash = dirName.IndexOf('-');
                        if (dash > 0)
                        {
                            if (mcVersion == "unknown")
                            {
                                mcVersion = dirName[..dash];
                                mcVersionSource = $"libraries/net/minecraftforge/forge/{dirName}";
                            }
                            if (loaderVersion == "unknown")
                            {
                                loaderVersion = dirName[(dash + 1)..];
                                loaderVersionSource = $"libraries/net/minecraftforge/forge/{dirName}";
                            }
                            break;
                        }
                    }
                }
                catch { }
            }

            // Fabric
            string fabricLib = Path.Combine(librariesDir, "net", "fabricmc", "fabric-loader");
            if (Directory.Exists(fabricLib))
            {
                loaderType = "fabric";
                loaderTypeSource = "libraries/net/fabricmc/fabric-loader";
                try
                {
                    string[] subDirs = Directory.GetDirectories(fabricLib);
                    if (subDirs.Length > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0]);
                        loaderVersion = verName;
                        loaderVersionSource = $"libraries/net/fabricmc/fabric-loader/{verName}";
                    }
                }
                catch { }
            }

            // Quilt
            string quiltLib = Path.Combine(librariesDir, "org", "quiltmc", "quilt-loader");
            if (Directory.Exists(quiltLib))
            {
                loaderType = "quilt";
                loaderTypeSource = "libraries/org/quiltmc/quilt-loader";
                try
                {
                    string[] subDirs = Directory.GetDirectories(quiltLib);
                    if (subDirs.Length > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0]);
                        loaderVersion = verName;
                        loaderVersionSource = $"libraries/org/quiltmc/quilt-loader/{verName}";
                    }
                }
                catch { }
            }
        }

        // 4. 從標準啟動檔名補充判斷載入器類型
        if (loaderType == "unknown")
        {
            if (files.Contains("fabric-server-launch.jar"))
            {
                loaderType = "fabric";
                loaderTypeSource = "fabric-server-launch.jar 啟動檔名";
            }
            else if (files.Contains("quilt-server-launch.jar"))
            {
                loaderType = "quilt";
                loaderTypeSource = "quilt-server-launch.jar 啟動檔名";
            }
            else if (target.Value.Equals("server.jar", StringComparison.OrdinalIgnoreCase) ||
                     target.Value.Equals("minecraft_server.jar", StringComparison.OrdinalIgnoreCase))
            {
                loaderType = "vanilla";
                loaderTypeSource = "官方標準 server.jar 檔名";
            }
        }

        // 5. 從主程式檔名解析 (如 forge-1.20.1-47.2.0.jar)
        string exeName = target.Value;
        var forgeMatch = ForgeJarRegex().Match(exeName);
        if (forgeMatch.Success)
        {
            if (mcVersion == "unknown")
            {
                mcVersion = forgeMatch.Groups[1].Value;
                mcVersionSource = $"{exeName} 檔名";
            }
            if (loaderVersion == "unknown")
            {
                loaderVersion = forgeMatch.Groups[2].Value;
                loaderVersionSource = $"{exeName} 檔名";
            }
            if (loaderType == "unknown")
            {
                loaderType = "forge";
                loaderTypeSource = $"{exeName} 檔名";
            }
        }
        else if (mcVersion == "unknown")
        {
            string? extractedMc = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(exeName);
            if (!string.IsNullOrEmpty(extractedMc))
            {
                mcVersion = extractedMc;
                mcVersionSource = $"{exeName} 檔名";
            }
        }

        // 6. 掃描 run.bat / win_args.txt 內容
        if (mcVersion == "unknown" || loaderVersion == "unknown")
        {
            string runBat = Path.Combine(directory, "run.bat");
            string winArgs = Path.Combine(directory, "win_args.txt");
            string toCheck = File.Exists(runBat) ? runBat : (File.Exists(winArgs) ? winArgs : string.Empty);
            if (!string.IsNullOrEmpty(toCheck))
            {
                try
                {
                    string content = File.ReadAllText(toCheck);
                    var m = ForgeJarRegex().Match(content);
                    if (m.Success)
                    {
                        if (mcVersion == "unknown")
                        {
                            mcVersion = m.Groups[1].Value;
                            mcVersionSource = $"{Path.GetFileName(toCheck)} 腳本內容";
                        }
                        if (loaderVersion == "unknown")
                        {
                            loaderVersion = m.Groups[2].Value;
                            loaderVersionSource = $"{Path.GetFileName(toCheck)} 腳本內容";
                        }
                        if (loaderType == "unknown")
                        {
                            loaderType = "forge";
                            loaderTypeSource = $"{Path.GetFileName(toCheck)} 腳本內容";
                        }
                    }
                }
                catch { }
            }
        }

        // 7. 檢查 logs/latest.log 或最新修改之日誌檔
        if (mcVersion == "unknown" || loaderVersion == "unknown")
        {
            string? logFile = FindLatestLogFile(directory);
            if (logFile is not null && File.Exists(logFile))
            {
                try
                {
                    using var sr = new StreamReader(logFile, Encoding.UTF8);
                    int lineCount = 0;
                    string? line;
                    while ((line = sr.ReadLine()) is not null && lineCount++ < 2000)
                    {
                        if (mcVersion == "unknown")
                        {
                            var mcMatch = McLogRegex().Match(line);
                            if (mcMatch.Success)
                            {
                                mcVersion = mcMatch.Groups[1].Value;
                                mcVersionSource = $"{Path.GetFileName(logFile)} 啟動日誌";
                            }
                        }

                        if (loaderVersion == "unknown")
                        {
                            var forgeM = ForgeLogRegex().Match(line);
                            if (forgeM.Success)
                            {
                                loaderVersion = forgeM.Groups[1].Value;
                                loaderVersionSource = $"{Path.GetFileName(logFile)} 載入器日誌";
                                if (loaderType == "unknown")
                                {
                                    loaderType = "forge";
                                    loaderTypeSource = $"{Path.GetFileName(logFile)} 載入器日誌";
                                }
                            }
                            else
                            {
                                var neoM = NeoForgeLogRegex().Match(line);
                                if (neoM.Success)
                                {
                                    loaderVersion = neoM.Groups[1].Value;
                                    loaderVersionSource = $"{Path.GetFileName(logFile)} 載入器日誌";
                                    if (loaderType == "unknown")
                                    {
                                        loaderType = "neoforge";
                                        loaderTypeSource = $"{Path.GetFileName(logFile)} 載入器日誌";
                                    }
                                }
                            }
                        }

                        if (mcVersion != "unknown" && loaderVersion != "unknown")
                        {
                            break;
                        }
                    }
                }
                catch { }
            }
        }

        return (loaderType, loaderVersion, mcVersion, loaderTypeSource, loaderVersionSource, mcVersionSource);
    }

    private static string? FindLatestLogFile(string serverDirectory)
    {
        string logsDir = Path.Combine(serverDirectory, "logs");
        if (Directory.Exists(logsDir))
        {
            string latestLog = Path.Combine(logsDir, "latest.log");
            if (File.Exists(latestLog))
            {
                return latestLog;
            }

            try
            {
                var dirInfo = new DirectoryInfo(logsDir);
                var newest = dirInfo.EnumerateFiles("*.log")
                    .OrderByDescending(f => f.LastWriteTimeUtc)
                    .FirstOrDefault();
                if (newest is not null)
                {
                    return newest.FullName;
                }
            }
            catch { }
        }

        string rootLog = Path.Combine(serverDirectory, "server.log");
        return File.Exists(rootLog) ? rootLog : null;
    }

    private static string? TryExtractMinecraftVersionFromRootJson(string directory)
    {
        string jsonPath = Path.Combine(directory, "version.json");
        if (!File.Exists(jsonPath))
        {
            return null;
        }

        try
        {
            using var stream = File.OpenRead(jsonPath);
            using var doc = JsonDocument.Parse(stream);
            var root = doc.RootElement;
            foreach (string prop in (ReadOnlySpan<string>)["id", "name", "release_target"])
            {
                if (root.TryGetProperty(prop, out var val))
                {
                    string? str = val.GetString();
                    if (!string.IsNullOrEmpty(str))
                    {
                        string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(str);
                        if (!string.IsNullOrEmpty(extracted))
                        {
                            return extracted;
                        }
                    }
                }
            }
        }
        catch { }
        return null;
    }

    private static string? TryExtractMinecraftVersionFromJar(string jarPath)
    {
        try
        {
            using var zip = ZipFile.OpenRead(jarPath);
            var versionEntry = zip.GetEntry("version.json");
            if (versionEntry is not null)
            {
                using var stream = versionEntry.Open();
                using var doc = JsonDocument.Parse(stream);
                var root = doc.RootElement;
                foreach (string prop in (ReadOnlySpan<string>)["id", "name", "release_target"])
                {
                    if (root.TryGetProperty(prop, out var val))
                    {
                        string? str = val.GetString();
                        if (!string.IsNullOrEmpty(str))
                        {
                            string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(str);
                            if (!string.IsNullOrEmpty(extracted))
                            {
                                return extracted;
                            }
                        }
                    }
                }
            }

            var manifestEntry = zip.GetEntry("META-INF/MANIFEST.MF");
            if (manifestEntry is not null)
            {
                using var stream = manifestEntry.Open();
                using var reader = new StreamReader(stream, Encoding.UTF8);
                string manifestText = reader.ReadToEnd();
                string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(manifestText);
                if (!string.IsNullOrEmpty(extracted))
                {
                    return extracted;
                }
            }
        }
        catch { }
        return null;
    }

    private static string? DeriveMinecraftVersionFromNeoForge(string rawVersion)
    {
        string[] parts = rawVersion.Split('.');
        if (parts.Length >= 2 && int.TryParse(parts[0], out int major) && major >= 20)
        {
            string minor = parts[1].Split('-')[0];
            return $"1.{major}.{minor}";
        }
        return null;
    }

    private static (int MaxMb, int? MinMb) InspectMemory(string directory)
    {
        int maxMb = 2048;
        int? minMb = null;

        string argsFile = Path.Combine(directory, "user_jvm_args.txt");
        if (File.Exists(argsFile))
        {
            try
            {
                foreach (string line in File.ReadAllLines(argsFile))
                {
                    string trimmed = line.Trim();
                    if (trimmed.StartsWith('#'))
                    {
                        continue;
                    }

                    int? xmx = MemoryUtils.ParseMemorySetting(trimmed, "Xmx");
                    if (xmx.HasValue)
                    {
                        maxMb = xmx.Value;
                    }

                    int? xms = MemoryUtils.ParseMemorySetting(trimmed, "Xms");
                    if (xms.HasValue)
                    {
                        minMb = xms.Value;
                    }
                }
            }
            catch
            {
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

    [GeneratedRegex(@"NeoForge\s+(?:version\s+|v)?(\d+\.\d+\.\d+)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex NeoForgeLogRegex();
}
