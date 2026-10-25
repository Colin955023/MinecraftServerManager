using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed partial class ServerInspector : IServerInspector
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerInspector");
    private readonly IServerDirectorySizeService _directorySizeService;

    public ServerInspector(IServerDirectorySizeService directorySizeService)
    {
        ArgumentNullException.ThrowIfNull(directorySizeService);
        _directorySizeService = directorySizeService;
    }

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

    public async Task<ServerInspection> InspectAsync(
        string serverDirectory,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        try
        {
            string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
            if (!SafeFileSystem.DirectoryExists(stableDir))
            {
                return new ServerInspection(
                    path: serverDirectory,
                    revision: string.Empty,
                    isCandidate: false,
                    error: "找不到伺服器目錄");
            }

            var entries = SafeFileSystem.ListBoundedDirectory(stableDir, maxEntries: 512, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false);
            var files = entries.Where(static e => !e.IsDirectory).Select(static e => Path.GetFileName(e.FullPath)).ToHashSet(StringComparer.OrdinalIgnoreCase);

            var eulaState = InspectEula(stableDir, files);
            var launchTarget = InspectLaunchTarget(stableDir, files);
            var (loaderType, loaderVersion, mcVersion, loaderTypeSource, loaderVersionSource, mcVersionSource) =
                InspectLoaderAndVersion(stableDir, files, launchTarget);
            var (maxMb, minMb) = InspectMemory(stableDir);
            long totalSizeBytes = await _directorySizeService.CalculateServerSizeAsync(stableDir, cancellationToken).ConfigureAwait(false);

            bool isCandidate = launchTarget.Kind != LaunchTargetKind.None || files.Contains(ServerDefaults.ServerPropertiesFileName);
            bool launchable = launchTarget.Kind != LaunchTargetKind.None && eulaState == EulaState.Accepted;
            bool statusReady = launchable && MinecraftVersion.TryParse(mcVersion, out _);

            var revisionBuilder = new StringBuilder();
            foreach (string? file in files.OrderBy(static f => f, StringComparer.OrdinalIgnoreCase))
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

            return new ServerInspection(
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
                totalSizeBytes: totalSizeBytes);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "伺服器偵測發生例外: {Path}, 原因: {Message}", serverDirectory, ex.Message);
            return new ServerInspection(
                path: serverDirectory,
                revision: string.Empty,
                isCandidate: false,
                error: ex.Message);
        }
    }

    private static EulaState InspectEula(string directory, HashSet<string> files)
    {
        if (!files.Contains(ServerDefaults.EulaFileName))
        {
            return EulaState.Missing;
        }

        try
        {
            string path = Path.Combine(directory, ServerDefaults.EulaFileName);
            if (SafeFileSystem.GetFileLength(path) > MaxMetadataBytes)
            {
                return EulaState.Missing;
            }

            string content = SafeFileSystem.ReadAllText(path, Encoding.UTF8);
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
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning("讀取 eula.txt 失敗: {Message}", ex.Message);
            return EulaState.Missing;
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
            if (file.EndsWith(".jar", StringComparison.OrdinalIgnoreCase) && !candidates.Contains(file))
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
        string? loaderType = null;
        string? loaderVersion = null;
        string? mcVersion = null;
        string loaderTypeSource = "未偵測到";
        string loaderVersionSource = "未偵測到";
        string mcVersionSource = "未偵測到";

        string librariesDir = Path.Combine(directory, "libraries");
        bool hasLibraries = SafeFileSystem.DirectoryExists(librariesDir);

        // 1. 檢查伺服器根目錄下的 version.json
        string? rootJsonMc = TryExtractMinecraftVersionFromRootJson(directory);
        if (!string.IsNullOrEmpty(rootJsonMc))
        {
            mcVersion = rootJsonMc;
            mcVersionSource = "根目錄 version.json";
        }

        // 2. 檢查主程式 JAR 內部 metadata (version.json 與 MANIFEST.MF)
        if (mcVersion is null)
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

            if (primaryJarPath is not null && SafeFileSystem.FileExists(primaryJarPath))
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
            if (SafeFileSystem.DirectoryExists(neoLib))
            {
                loaderType = "neoforge";
                loaderTypeSource = "libraries/net/neoforged/neoforge";
                try
                {
                    var subDirs = SafeFileSystem.ListBoundedDirectory(neoLib, maxEntries: 16, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
                        .Where(static e => e.IsDirectory)
                        .ToList();
                    if (subDirs.Count > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0].FullPath);
                        loaderVersion = verName;
                        loaderVersionSource = $"libraries/net/neoforged/neoforge/{verName}";
                        string? derived = MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge(verName);
                        if (!string.IsNullOrEmpty(derived) && mcVersion is null)
                        {
                            mcVersion = derived;
                            mcVersionSource = $"從 NeoForge {verName} 推導";
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning("探測 NeoForge 函式庫目錄失敗: {Message}", ex.Message);
                }
            }

            // Forge
            string forgeLib = Path.Combine(librariesDir, "net", "minecraftforge", "forge");
            if (SafeFileSystem.DirectoryExists(forgeLib))
            {
                loaderType = "forge";
                loaderTypeSource = "libraries/net/minecraftforge/forge";
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
                            if (mcVersion is null)
                            {
                                mcVersion = dirName[..dash];
                                mcVersionSource = $"libraries/net/minecraftforge/forge/{dirName}";
                            }
                            if (loaderVersion is null)
                            {
                                loaderVersion = dirName[(dash + 1)..];
                                loaderVersionSource = $"libraries/net/minecraftforge/forge/{dirName}";
                            }
                            break;
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning("探測 Forge 函式庫目錄失敗: {Message}", ex.Message);
                }
            }

            // Fabric
            string fabricLib = Path.Combine(librariesDir, "net", "fabricmc", "fabric-loader");
            if (SafeFileSystem.DirectoryExists(fabricLib))
            {
                loaderType = "fabric";
                loaderTypeSource = "libraries/net/fabricmc/fabric-loader";
                try
                {
                    var subDirs = SafeFileSystem.ListBoundedDirectory(fabricLib, maxEntries: 16, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
                        .Where(static e => e.IsDirectory)
                        .ToList();
                    if (subDirs.Count > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0].FullPath);
                        loaderVersion = verName;
                        loaderVersionSource = $"libraries/net/fabricmc/fabric-loader/{verName}";
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning("探測 Fabric 函式庫目錄失敗: {Message}", ex.Message);
                }
            }

            // Quilt
            string quiltLib = Path.Combine(librariesDir, "org", "quiltmc", "quilt-loader");
            if (SafeFileSystem.DirectoryExists(quiltLib))
            {
                loaderType = "quilt";
                loaderTypeSource = "libraries/org/quiltmc/quilt-loader";
                try
                {
                    var subDirs = SafeFileSystem.ListBoundedDirectory(quiltLib, maxEntries: 16, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
                        .Where(static e => e.IsDirectory)
                        .ToList();
                    if (subDirs.Count > 0)
                    {
                        string verName = Path.GetFileName(subDirs[0].FullPath);
                        loaderVersion = verName;
                        loaderVersionSource = $"libraries/org/quiltmc/quilt-loader/{verName}";
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning("探測 Quilt 函式庫目錄失敗: {Message}", ex.Message);
                }
            }
        }

        // 4. 從標準啟動檔名或特徵設定檔判斷載入器類型
        if (loaderType is null)
        {
            if (target.Value.StartsWith("paper", StringComparison.OrdinalIgnoreCase) ||
                files.Any(static f => f.StartsWith("paper-", StringComparison.OrdinalIgnoreCase) && f.EndsWith(".jar", StringComparison.OrdinalIgnoreCase)) ||
                files.Contains("paper-global.yml") || files.Contains("paper.yml") || files.Contains("paper-world-defaults.yml"))
            {
                loaderType = "paper";
                loaderTypeSource = "Paper 伺服器特徵 (paper.jar 或 paper-global.yml)";
            }
            else if (files.Contains("fabric-server-launch.jar"))
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

        // 5. 從主程式檔名解析 (如 paper-1.21.4-165.jar 或 forge-1.20.1-47.2.0.jar)
        string exeName = target.Value;
        var paperMatch = PaperJarRegex().Match(exeName);
        if (paperMatch.Success)
        {
            if (mcVersion is null)
            {
                mcVersion = paperMatch.Groups["mcVer"].Value;
                mcVersionSource = $"{exeName} 檔名";
            }
            if (loaderVersion is null)
            {
                loaderVersion = paperMatch.Groups["build"].Value;
                loaderVersionSource = $"{exeName} 檔名";
            }
            loaderType = "paper";
            loaderTypeSource = $"{exeName} 檔名";
        }

        var forgeMatch = ForgeJarRegex().Match(exeName);
        if (forgeMatch.Success)
        {
            if (mcVersion is null)
            {
                mcVersion = forgeMatch.Groups[1].Value;
                mcVersionSource = $"{exeName} 檔名";
            }
            if (loaderVersion is null)
            {
                loaderVersion = forgeMatch.Groups[2].Value;
                loaderVersionSource = $"{exeName} 檔名";
            }
            if (loaderType is null)
            {
                loaderType = "forge";
                loaderTypeSource = $"{exeName} 檔名";
            }
        }
        else if (mcVersion is null)
        {
            string? extractedMc = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(exeName);
            if (!string.IsNullOrEmpty(extractedMc))
            {
                mcVersion = extractedMc;
                mcVersionSource = $"{exeName} 檔名";
            }
        }

        // 6. 掃描 run.bat / win_args.txt 內容
        if (mcVersion is null || loaderVersion is null)
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
                        if (mcVersion is null)
                        {
                            mcVersion = m.Groups[1].Value;
                            mcVersionSource = $"{Path.GetFileName(toCheck)} 腳本內容";
                        }
                        if (loaderVersion is null)
                        {
                            loaderVersion = m.Groups[2].Value;
                            loaderVersionSource = $"{Path.GetFileName(toCheck)} 腳本內容";
                        }
                        if (loaderType is null)
                        {
                            loaderType = "forge";
                            loaderTypeSource = $"{Path.GetFileName(toCheck)} 腳本內容";
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning("檢查啟動腳本失敗: {Message}", ex.Message);
                }
            }
        }

        // 7. 檢查 logs/latest.log 或最新修改之記錄檔
        if (mcVersion is null || loaderVersion is null)
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
                        if (mcVersion is null)
                        {
                            var mcMatch = McLogRegex().Match(line);
                            if (mcMatch.Success)
                            {
                                mcVersion = mcMatch.Groups[1].Value;
                                mcVersionSource = $"{Path.GetFileName(logFile)} 啟動記錄";
                            }
                        }

                        if (loaderVersion is null)
                        {
                            var forgeM = ForgeLogRegex().Match(line);
                            if (forgeM.Success)
                            {
                                loaderVersion = forgeM.Groups[1].Value;
                                loaderVersionSource = $"{Path.GetFileName(logFile)} 載入器記錄";
                                if (loaderType is null)
                                {
                                    loaderType = "forge";
                                    loaderTypeSource = $"{Path.GetFileName(logFile)} 載入器記錄";
                                }
                            }
                            else
                            {
                                var neoM = NeoForgeLogRegex().Match(line);
                                if (neoM.Success)
                                {
                                    loaderVersion = neoM.Groups[1].Value;
                                    loaderVersionSource = $"{Path.GetFileName(logFile)} 載入器記錄";
                                    if (loaderType is null)
                                    {
                                        loaderType = "neoforge";
                                        loaderTypeSource = $"{Path.GetFileName(logFile)} 載入器記錄";
                                    }
                                }
                            }
                        }

                        if (mcVersion is not null && loaderVersion is not null)
                        {
                            break;
                        }
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning("讀取伺服器記錄檔失敗: {Message}", ex.Message);
                }
            }
        }

        if (string.Equals(loaderType, "vanilla", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(loaderVersion))
            {
                loaderVersion = mcVersion;
                loaderVersionSource = mcVersionSource;
            }
        }

        return (loaderType ?? "unknown", loaderVersion ?? "unknown", mcVersion ?? "unknown", loaderTypeSource, loaderVersionSource, mcVersionSource);
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
                string? newest = SafeFileSystem.EnumerateFiles(logsDir, "*.log")
                    .OrderByDescending(SafeFileSystem.GetFileLastWriteTimeUtc)
                    .FirstOrDefault();
                if (newest is not null)
                {
                    return newest;
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning("尋找最新記錄檔失敗: {Message}", ex.Message);
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
            long fileLength = SafeFileSystem.GetFileLength(jsonPath);
            if (fileLength > MaxMetadataBytes)
            {
                Logger.Warning("version.json 檔案超過安全大小上限 ({Size} bytes)，略過解析", fileLength);
                return null;
            }

            using var stream = SafeFileSystem.OpenRead(jsonPath);
            byte[]? payload = ReadBoundedBytes(stream, MaxMetadataBytes);
            if (payload is null)
            {
                return null;
            }

            using var doc = JsonCodec.ParseDocument(payload);
            var root = doc.RootElement;
            foreach (string prop in VersionJsonCandidateProperties)
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
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            Logger.Warning("解析 version.json 失敗: {Message}", ex.Message);
        }
        return null;
    }

    private static string? TryExtractMinecraftVersionFromJar(string jarPath)
    {
        try
        {
            using var zip = SafeZipArchive.OpenRead(jarPath);
            var versionEntry = zip.GetEntry("version.json");
            if (versionEntry is not null && versionEntry.Length <= MaxMetadataBytes)
            {
                using var stream = versionEntry.Open();
                byte[]? versionBytes = ReadBoundedBytes(stream, MaxMetadataBytes);
                if (versionBytes is not null)
                {
                    using var doc = JsonCodec.ParseDocument(versionBytes);
                    var root = doc.RootElement;
                    foreach (string prop in VersionJsonCandidateProperties)
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
            }

            var manifestEntry = zip.GetEntry("META-INF/MANIFEST.MF");
            if (manifestEntry is not null && manifestEntry.Length <= MaxMetadataBytes)
            {
                using var stream = manifestEntry.Open();
                byte[]? manifestBytes = ReadBoundedBytes(stream, MaxMetadataBytes);
                if (manifestBytes is not null)
                {
                    string manifestText = Encoding.UTF8.GetString(manifestBytes);
                    string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(manifestText);
                    if (!string.IsNullOrEmpty(extracted))
                    {
                        return extracted;
                    }
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or JsonException)
        {
            Logger.Warning("解析 JAR 清單版本失敗: {Message}", ex.Message);
        }
        return null;
    }

    private static byte[]? ReadBoundedBytes(Stream stream, long maxBytes)
    {
        using var memoryStream = new MemoryStream();
        byte[] buffer = new byte[8192];
        int read;
        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            if (memoryStream.Length + read > maxBytes)
            {
                return null;
            }

            memoryStream.Write(buffer, 0, read);
        }

        return memoryStream.ToArray();
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

            foreach (string line in SafeFileSystem.ReadAllLines(filePath))
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
            Logger.Warning("讀取檔案記憶體設定失敗 ({Path}): {Message}", filePath, ex.Message);
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
                Logger.Warning("掃描子目錄記憶體設定失敗: {Message}", ex.Message);
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
