using System.Collections.Frozen;
using System.Globalization;
using System.Text;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器集中管理服務實作
/// </summary>
public sealed partial class ServerManager : IServerManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerManager");
    private static readonly string[] PreferredLaunchJars =
    [
        "paper.jar",
        "fabric-server-launch.jar",
        "quilt-server-launch.jar",
        "server.jar",
        "minecraft_server.jar",
    ];
    private readonly string _serversRoot;
    private readonly string _registryFilePath;
    private readonly IServerInspector _inspector;
    private readonly ILoaderInstallerService? _loaderInstaller;
    private readonly IJavaRuntimeDetector? _javaDetector;
    private readonly IMinecraftJavaRequirementService? _javaRequirementService;
    private readonly Lock _lock = new();
    private Dictionary<string, ServerConfigPayload>? _cachedRegistry;
    private DateTime _lastRegistryWriteTimeUtc;

    public ServerManager(
        string serversRoot,
        IServerInspector? inspector = null,
        ILoaderInstallerService? loaderInstaller = null,
        IJavaRuntimeDetector? javaDetector = null,
        IMinecraftJavaRequirementService? javaRequirementService = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        _serversRoot = SafeFileSystem.ResolveStableDirectory(serversRoot, create: true);
        _registryFilePath = Path.Combine(_serversRoot, "servers.json");
        _inspector = inspector ?? new ServerInspector();
        _loaderInstaller = loaderInstaller;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;

        ServerTombstoneManager.RecoverDeleteTombstones(
            _serversRoot,
            serverName =>
            {
                var registry = LoadRegistry();
                return registry.TryGetValue(serverName, out var cfg) ? cfg.Path : null;
            });
    }

    public Task<IReadOnlyList<ServerConfig>> GetAllServersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        lock (_lock)
        {
            var registry = LoadRegistry();
            var result = new List<ServerConfig>();
            foreach (var payload in registry.Values)
            {
                bool validName = ServerName.TryParse(payload.Name, out var name);
                bool validMc = MinecraftVersion.TryParse(payload.MinecraftVersion, out var mcVer);
                bool validLoader = Enum.TryParse<LoaderKind>(payload.LoaderType, ignoreCase: true, out var loader);

                if (validName && validMc && validLoader)
                {
                    result.Add(new ServerConfig(
                        name: name,
                        minecraftVersion: mcVer,
                        loaderType: loader,
                        loaderVersion: payload.LoaderVersion ?? string.Empty,
                        memoryMaxMb: payload.MemoryMaxMb > 0 ? payload.MemoryMaxMb : 2048,
                        memoryMinMb: payload.MemoryMinMb,
                        path: payload.Path ?? Path.Combine(_serversRoot, payload.Name),
                        jvmArgs: payload.JvmArgs,
                        backupPath: payload.BackupPath ?? string.Empty));
                }
            }

            return Task.FromResult<IReadOnlyList<ServerConfig>>(result);
        }
    }

    public Task<ServerConfig?> GetServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        cancellationToken.ThrowIfCancellationRequested();
        lock (_lock)
        {
            var registry = LoadRegistry();
            if (registry.TryGetValue(name, out var payload))
            {
                bool validName = ServerName.TryParse(payload.Name, out var serverName);
                bool validMc = MinecraftVersion.TryParse(payload.MinecraftVersion, out var mcVer);
                bool validLoader = Enum.TryParse<LoaderKind>(payload.LoaderType, ignoreCase: true, out var loader);

                if (validName && validMc && validLoader)
                {
                    var config = new ServerConfig(
                        name: serverName,
                        minecraftVersion: mcVer,
                        loaderType: loader,
                        loaderVersion: payload.LoaderVersion ?? string.Empty,
                        memoryMaxMb: payload.MemoryMaxMb > 0 ? payload.MemoryMaxMb : 2048,
                        memoryMinMb: payload.MemoryMinMb,
                        path: payload.Path ?? Path.Combine(_serversRoot, payload.Name),
                        jvmArgs: payload.JvmArgs,
                        backupPath: payload.BackupPath ?? string.Empty);
                    return Task.FromResult<ServerConfig?>(config);
                }
            }

            return Task.FromResult<ServerConfig?>(null);
        }
    }

    public async Task<ServerCreationResult> CreateServerAsync(
        ServerCreationPlan plan,
        IProgress<ServerCreationProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(plan);
        cancellationToken.ThrowIfCancellationRequested();

        // ── Phase 1: Validate (0% ~ 5%) ──
        progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Validate, 0, "正在驗證伺服器名稱與目錄..."));

        var existing = await GetServerAsync(plan.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            return ServerCreationResult.Failed($"已存在同名的伺服器：{plan.Name.Value}");
        }

        string serverDir = Path.Combine(_serversRoot, plan.Name.Value);
        if (SafeFileSystem.DirectoryExists(serverDir) && SafeFileSystem.EnumerateFileSystemEntries(serverDir).Any())
        {
            return ServerCreationResult.Failed($"目標目錄已存在且非空：{serverDir}");
        }

        string? insufficientSpace = CheckFreeSpace(_serversRoot, 500L * 1024 * 1024);
        if (insufficientSpace is not null)
        {
            return ServerCreationResult.Failed(insufficientSpace);
        }

        bool createdDir = false;
        string stagingDir = Path.Combine(_serversRoot, $".create-staging-{Guid.NewGuid():N}");

        Logger.Information("開始建立伺服器「{Name}」 (MC: {McVer}, 載入器: {Loader} {LoaderVer}, 記憶體: {MemMax}MB)", plan.Name.Value, plan.MinecraftVersion.Value, plan.LoaderType, plan.LoaderVersion, plan.MemoryMaxMb);

        try
        {
            // ── Phase 2: Stage (5% ~ 15%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 5, "正在建立暫存目錄與初始設定檔..."));

            string stableStaging = SafeFileSystem.ResolveStableDirectory(stagingDir, create: true);
            createdDir = true;

            // 寫入 eula.txt
            string eulaPath = Path.Combine(stableStaging, "eula.txt");
            AtomicFileWriter.WriteText(eulaPath, "eula=true\n");

            // 寫入初始 server.properties（含 MOTD 與 Port）
            string propertiesPath = Path.Combine(stableStaging, "server.properties");
            var initialProps = new Dictionary<string, string>(ServerPropertiesMetadata.DefaultProperties)
            {
                ["motd"] = $"A Minecraft Server ({plan.Name.Value})",
                ["server-port"] = "25565",
            };

            // 套用建立計畫中指定的自訂屬性
            foreach (var entry in plan.Properties)
            {
                initialProps[entry.Key] = entry.Value;
            }

            string propsText = PropertiesDocumentCodec.Serialize(initialProps);
            AtomicFileWriter.WriteText(propertiesPath, propsText);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 15, "初始設定檔已建立"));

            // ── Phase 3: Artifact (15% ~ 85%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 15, "正在下載伺服器核心..."));

            string? resolvedJavaPath = await ResolveJavaExecutableAsync(plan.UserJavaPath, plan.MinecraftVersion.Value, plan.LoaderType, cancellationToken).ConfigureAwait(false);

            if (_loaderInstaller is not null)
            {
                int lastArtifactPct = 15;
                var loaderProgress = progress is null ? null : new Progress<LoaderInstallProgress>(lp =>
                {
                    int mappedPct = 15 + (int)(lp.PercentCompleted * 0.70); // 15% ~ 85%
                    int clamped = Math.Clamp(mappedPct, 15, 85);
                    lock (plan)
                    {
                        clamped = Math.Max(lastArtifactPct, clamped);
                        lastArtifactPct = clamped;
                    }
                    progress.Report(new ServerCreationProgressReport(
                        ServerCreationPhase.Artifact, clamped, lp.Message));
                });

                await _loaderInstaller.InstallLoaderAsync(
                    loader: plan.LoaderType,
                    minecraftVersion: plan.MinecraftVersion.Value,
                    loaderVersion: plan.LoaderVersion,
                    serverDirectory: stableStaging,
                    javaExecutablePath: resolvedJavaPath ?? "java",
                    progress: loaderProgress,
                    cancellationToken: cancellationToken).ConfigureAwait(false);
            }

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 85, "伺服器核心安裝完成"));

            // ── Phase 4: LaunchScript (85% ~ 95%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.LaunchScript, 85, "正在生成啟動腳本..."));

            string? launchJar = DetectLaunchJar(stableStaging);
            if (launchJar is null)
            {
                if (_loaderInstaller is not null)
                {
                    return ServerCreationResult.Failed("找不到可用的啟器 JAR 或參數設定檔，伺服器核心可能下載失敗");
                }

                // 未提供安裝器時以預設檔名生成腳本
                launchJar = "server.jar";
            }

            WriteStartScript(stableStaging, launchJar, plan.MemoryMaxMb, plan.MemoryMinMb ?? 1024, resolvedJavaPath, plan.JvmArgs);
            CleanupRedundantStartupScripts(stableStaging);
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.LaunchScript, 95, "啟動腳本已生成並通過完整性驗證"));

            // ── Phase 5: Commit (95% ~ 100%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Commit, 95, "正在登錄伺服器設定..."));

            if (SafeFileSystem.DirectoryExists(serverDir))
            {
                SafeFileSystem.DeleteDirectory(serverDir, recursive: false);
            }

            if (!SafeFileSystem.MoveWithin(_serversRoot, stableStaging, serverDir))
            {
                return ServerCreationResult.Failed("原子移動暫存目錄至正式伺服器目錄失敗");
            }

            var config = plan.BuildConfig(serverDir);
            if (plan.LoaderType is LoaderKind.Forge or LoaderKind.NeoForge ||
                SafeFileSystem.FileExists(Path.Combine(serverDir, "user_jvm_args.txt")) ||
                SafeFileSystem.FileExists(Path.Combine(serverDir, "run.bat")))
            {
                UpdateForgeUserJvmArgs(serverDir, config);
            }

            lock (_lock)
            {
                var registry = LoadRegistry();
                registry[plan.Name.Value] = ServerConfigPayload.FromDomain(config);
                SaveRegistry(registry);
            }

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Commit, 100, "伺服器建立完成！"));
            Logger.Information("伺服器「{Name}」建立成功！路徑: {Path}", plan.Name.Value, serverDir);
            return ServerCreationResult.Success(config);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器「{Name}」失敗: {Message}", plan.Name.Value, ex.Message);
            if (createdDir)
            {
                ReadOnlySpan<string> cleanupTargets = [stagingDir, serverDir];
                foreach (string cleanupTarget in cleanupTargets)
                {
                    try
                    {
                        if (SafeFileSystem.DirectoryExists(cleanupTarget))
                        {
                            SafeFileSystem.DeleteWithin(_serversRoot, cleanupTarget);
                        }
                    }
                    catch
                    {
                    }
                }
            }
            return ServerCreationResult.Failed($"建立伺服器時發生例外：{ex.Message}");
        }
        finally
        {
            // 清理殘留暫存目錄
            try
            {
                if (createdDir && SafeFileSystem.DirectoryExists(stagingDir))
                {
                    SafeFileSystem.DeleteWithin(_serversRoot, stagingDir);
                }
            }
            catch
            {
            }
        }
    }

    /// <summary>
    /// 檢查目標磁碟可用空間是否足夠。
    /// </summary>
    private static string? CheckFreeSpace(string directory, long requiredBytes)
    {
        long? freeSpace = SafeFileSystem.GetAvailableFreeSpace(directory);
        if (freeSpace.HasValue && freeSpace.Value < requiredBytes)
        {
            string? root = Path.GetPathRoot(Path.GetFullPath(directory));
            return $"磁碟 {root} 可用空間不足（需要至少 {requiredBytes / (1024 * 1024)} MB）";
        }

        return null;
    }

    /// <summary>
    /// 偵測主啟動 JAR 或引數檔檔名。
    /// </summary>
    private static string? DetectLaunchJar(string directory)
    {
        // 優先從 Forge / NeoForge 的 run.bat 提取 win_args.txt
        string runBat = Path.Combine(directory, "run.bat");
        if (SafeFileSystem.FileExists(runBat))
        {
            try
            {
                string runBatContent = SafeFileSystem.ReadAllText(runBat);
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
        string forgeLib = Path.Combine(directory, "libraries", "net", "minecraftforge", "forge");
        if (SafeFileSystem.DirectoryExists(forgeLib))
        {
            foreach (string sub in SafeFileSystem.EnumerateDirectories(forgeLib))
            {
                string winArgs = Path.Combine(sub, "win_args.txt");
                if (SafeFileSystem.FileExists(winArgs))
                {
                    return "@" + Path.GetRelativePath(directory, winArgs).Replace('\\', '/');
                }
            }
        }

        string neoLib = Path.Combine(directory, "libraries", "net", "neoforged", "neoforge");
        if (SafeFileSystem.DirectoryExists(neoLib))
        {
            foreach (string sub in SafeFileSystem.EnumerateDirectories(neoLib))
            {
                string winArgs = Path.Combine(sub, "win_args.txt");
                if (SafeFileSystem.FileExists(winArgs))
                {
                    return "@" + Path.GetRelativePath(directory, winArgs).Replace('\\', '/');
                }
            }
        }

        string? paperJar = SafeFileSystem.EnumerateFiles(directory, "paper*.jar")
            .Select(Path.GetFileName)
            .FirstOrDefault();
        if (paperJar is not null)
        {
            return paperJar;
        }

        foreach (string candidate in PreferredLaunchJars)
        {
            if (SafeFileSystem.FileExists(Path.Combine(directory, candidate)))
            {
                return candidate;
            }
        }

        string? anyJar = SafeFileSystem.EnumerateFiles(directory, "*.jar", SearchOption.TopDirectoryOnly)
            .Select(Path.GetFileName)
            .FirstOrDefault(static name => name is not null && !name.Contains("installer", StringComparison.OrdinalIgnoreCase));

        if (anyJar is not null)
        {
            return anyJar;
        }

        if (SafeFileSystem.FileExists(runBat))
        {
            return "run.bat";
        }

        return null;
    }

    /// <summary>
    /// 生成統一規範之 start_server.bat 啟動腳本。
    /// </summary>
    private static void WriteStartScript(
        string directory,
        string launchTarget,
        int memoryMaxMb,
        int memoryMinMb,
        string? javaPath,
        IReadOnlyList<string>? jvmArgs = null)
    {
        string resolvedPath = javaPath ?? string.Empty;
        if (!Path.IsPathRooted(resolvedPath))
        {
            string pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            resolvedPath = Path.Combine(pf, "Java", "bin", "java.exe");
        }

        string javaCommand = $"\"{resolvedPath}\"";
        var builder = new StringBuilder();
        builder.AppendLine("@echo off");
        builder.AppendLine("chcp 65001 > nul");
        builder.AppendLine("cd /d \"%~dp0\"");
        builder.AppendLine();

        string extraArgs = (jvmArgs is not null && jvmArgs.Count > 0)
            ? string.Join(" ", jvmArgs) + " "
            : string.Empty;

        if (launchTarget.StartsWith('@'))
        {
            string argsFile = launchTarget[1..].Trim('"');
            builder.AppendLine(CultureInfo.InvariantCulture, $"{javaCommand} -Xms{memoryMinMb}M -Xmx{memoryMaxMb}M {extraArgs}@\"{argsFile}\" nogui %*");
        }
        else
        {
            string jarName = launchTarget.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) ? "server.jar" : launchTarget;
            string guiFlag = jarName.StartsWith("paper", StringComparison.OrdinalIgnoreCase) ? "--nogui" : "nogui";
            builder.AppendLine(CultureInfo.InvariantCulture, $"{javaCommand} -Xms{memoryMinMb}M -Xmx{memoryMaxMb}M {extraArgs}-jar \"{jarName}\" {guiFlag} %*");
        }

        AtomicFileWriter.WriteText(Path.Combine(directory, "start_server.bat"), builder.ToString());
    }

    /// <summary>
    /// 更新 Forge / NeoForge 之 user_jvm_args.txt 啟動與記憶體參數檔案（原子安全寫入）
    /// </summary>
    public static void UpdateForgeUserJvmArgs(string serverDirectory, ServerConfig config)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(config);

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        var lines = new List<string>();

        var customJvmArgs = config.JvmArgs ?? [];
        if (!JvmOptionPolicy.HasGcOption(customJvmArgs))
        {
            var recommendedGc = JvmOptionPolicy.RecommendGcArgs(config.MemoryMaxMb, javaMajor: null, loaderType: config.LoaderType.ToString(), existingArgs: customJvmArgs);
            lines.AddRange(recommendedGc);
        }

        lines.AddRange(customJvmArgs);

        if (config.MemoryMinMb.HasValue)
        {
            lines.Add($"-Xms{config.MemoryMinMb.Value}M");
        }

        if (config.MemoryMaxMb > 0)
        {
            lines.Add($"-Xmx{config.MemoryMaxMb}M");
        }

        string userJvmArgsPath = Path.Combine(stableDir, "user_jvm_args.txt");
        string content = string.Join(Environment.NewLine, lines) + Environment.NewLine;
        AtomicFileWriter.WriteText(userJvmArgsPath, content);
        Logger.Information("已更新 Forge/NeoForge 參數檔: {Path}", userJvmArgsPath);
    }

    private async Task<string?> ResolveJavaExecutableAsync(
        string? configuredJava,
        string minecraftVersion,
        LoaderKind loader = LoaderKind.Unknown,
        CancellationToken cancellationToken = default)
    {
        if (!string.IsNullOrWhiteSpace(configuredJava) && !string.Equals(configuredJava.Trim(), "java", StringComparison.OrdinalIgnoreCase))
        {
            string trimmed = configuredJava.Trim();
            if (SafeFileSystem.FileExists(trimmed))
            {
                return trimmed;
            }
        }

        // 依據 Minecraft 版本尋找最合適的 Java 執行環境
        if (_javaRequirementService is not null && _javaDetector is not null)
        {
            try
            {
                int targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion, loader, cancellationToken).ConfigureAwait(false);
                var match = await _javaDetector.FindBestMatchAsync(targetMajor, cancellationToken).ConfigureAwait(false);
                if (match is not null && SafeFileSystem.FileExists(match.ExecutablePath))
                {
                    return match.ExecutablePath;
                }
            }
            catch (Exception ex)
            {
                Logger.Warning("依 Minecraft {Version} 與載入器 {Loader} 尋找 Java 失敗: {Message}", minecraftVersion, loader, ex.Message);
            }
        }

        if (_javaDetector is not null)
        {
            try
            {
                var list = await _javaDetector.DetectAsync(forceRefresh: false, cancellationToken: cancellationToken).ConfigureAwait(false);
                var best = list.Where(static j => j.Is64Bit).OrderByDescending(static j => j.MajorVersion).FirstOrDefault()
                           ?? list.OrderByDescending(static j => j.MajorVersion).FirstOrDefault();
                if (best is not null && SafeFileSystem.FileExists(best.ExecutablePath))
                {
                    return best.ExecutablePath;
                }
            }
            catch
            {
            }
        }

        // 搜尋系統 PATH 中的 java.exe 完整絕對路徑
        string? sysJava = FindSystemJavaExecutable();
        if (!string.IsNullOrWhiteSpace(sysJava) && SafeFileSystem.FileExists(sysJava))
        {
            return sysJava;
        }

        return null;
    }

    private static string? FindSystemJavaExecutable()
    {
        string? pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathEnv))
        {
            return null;
        }

        ReadOnlySpan<char> span = pathEnv.AsSpan();
        while (!span.IsEmpty)
        {
            int sepIndex = span.IndexOf(Path.PathSeparator);
            ReadOnlySpan<char> folderSpan = (sepIndex >= 0 ? span[..sepIndex] : span).Trim();
            span = sepIndex >= 0 ? span[(sepIndex + 1)..] : [];

            if (folderSpan.IsEmpty)
            {
                continue;
            }

            try
            {
                string candidate = Path.Combine(folderSpan.ToString(), "java.exe");
                if (SafeFileSystem.FileExists(candidate))
                {
                    return candidate;
                }
            }
            catch
            {
            }
        }

        return null;
    }

    private static readonly FrozenSet<string> KnownStartupStems = new[]
    {
        "start", "run", "server", "launch", "startserver", "serverstart", "minecraft_server", "play"
    }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 在伺服器目錄中只保留標準 start_server.bat，清理其他多餘的 .bat、.ps1 與 .sh 啟動腳本。
    /// </summary>
    private static void CleanupRedundantStartupScripts(string directory)
    {
        if (!SafeFileSystem.DirectoryExists(directory))
        {
            return;
        }

        try
        {
            var entries = SafeFileSystem.ListBoundedDirectory(directory, rejectReparse: false);
            foreach (var entry in entries)
            {
                if (entry.IsDirectory)
                {
                    continue;
                }

                string ext = Path.GetExtension(entry.FullPath);
                if (string.Equals(ext, ".bat", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(ext, ".cmd", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(ext, ".ps1", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(ext, ".sh", StringComparison.OrdinalIgnoreCase))
                {
                    string fileName = Path.GetFileName(entry.FullPath);
                    if (string.Equals(fileName, "start_server.bat", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(fileName, "start_server.bat.bak", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    string stem = Path.GetFileNameWithoutExtension(entry.FullPath);
                    if (KnownStartupStems.Contains(stem))
                    {
                        try
                        {
                            SafeFileSystem.DeleteWithin(directory, entry.FullPath);
                            Logger.Information("已清理多餘啟動腳本: {File}", fileName);
                        }
                        catch (Exception ex)
                        {
                            Logger.Warning("清理多餘腳本 {File} 失敗: {Message}", fileName, ex.Message);
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("清理多餘啟動腳本失敗: {Message}", ex.Message);
        }
    }

    [GeneratedRegex(@"(?i)@([^\s""]+win_args\.txt)")]
    private static partial Regex WinArgsRegex();

    public async Task<ServerOperationResult> DeleteServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        cancellationToken.ThrowIfCancellationRequested();

        var config = await GetServerAsync(name, cancellationToken).ConfigureAwait(false);
        if (config is null)
        {
            return ServerOperationResult.Fail($"找不到伺服器：{name}");
        }

        string serverDir = Path.Combine(_serversRoot, name);

        Logger.Information("開始刪除伺服器「{Name}」...", name);

        try
        {
            // 兩階段安全刪除
            if (SafeFileSystem.DirectoryExists(serverDir))
            {
                var (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(_serversRoot, name, serverDir);
                lock (_lock)
                {
                    var registry = LoadRegistry();
                    registry.Remove(name);
                    SaveRegistry(registry);
                }

                ServerTombstoneManager.CleanTombstone(_serversRoot, tombstonePath, journalPath);
            }
            else
            {
                lock (_lock)
                {
                    var registry = LoadRegistry();
                    registry.Remove(name);
                    SaveRegistry(registry);
                }
            }

            Logger.Information("伺服器「{Name}」已完全刪除並清理完畢", name);
            return ServerOperationResult.Ok($"成功刪除伺服器：{name}");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "刪除伺服器「{Name}」失敗: {Message}", name, ex.Message);
            return ServerOperationResult.Fail($"刪除伺服器失敗：{ex.Message}");
        }
    }

    public async Task<ServerOperationResult> UpdateServerAsync(ServerConfig config, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(config);
        cancellationToken.ThrowIfCancellationRequested();

        var existing = await GetServerAsync(config.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is null)
        {
            return ServerOperationResult.Fail($"找不到要更新的伺服器：{config.Name.Value}");
        }

        lock (_lock)
        {
            var registry = LoadRegistry();
            registry[config.Name.Value] = ServerConfigPayload.FromDomain(config);
            SaveRegistry(registry);
        }

        if (SafeFileSystem.DirectoryExists(config.Path))
        {
            if (config.LoaderType is LoaderKind.Forge or LoaderKind.NeoForge ||
                SafeFileSystem.FileExists(Path.Combine(config.Path, "user_jvm_args.txt")) ||
                SafeFileSystem.FileExists(Path.Combine(config.Path, "run.bat")))
            {
                UpdateForgeUserJvmArgs(config.Path, config);
            }
        }

        string jvmText = config.JvmArgs is { Count: > 0 } ? string.Join(" ", config.JvmArgs) : "無";
        Logger.Information("伺服器「{Name}」設定更新成功 (記憶體: {Min}M-{Max}M, JVM參數: {Jvm})", config.Name.Value, config.MemoryMinMb, config.MemoryMaxMb, jvmText);
        return ServerOperationResult.Ok("更新伺服器設定成功");
    }

    public async Task<ServerImportResult> ImportServerAsync(
        string sourceDirectory,
        string targetName,
        ImportTransferMode mode = ImportTransferMode.Copy,
        IProgress<ServerImportProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(targetName);
        cancellationToken.ThrowIfCancellationRequested();

        Logger.Information("開始匯入伺服器「{Name}」 (來源: {Source}, 模式: {Mode})", targetName, sourceDirectory, mode);

        if (!ServerName.TryParse(targetName, out var serverName))
        {
            Logger.Warning("匯入伺服器名稱無效: {Name}", targetName);
            return ServerImportResult.Failed(targetName, "無效的伺服器名稱");
        }

        var existing = await GetServerAsync(targetName, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            Logger.Warning("匯入伺服器已存在同名者: {Name}", targetName);
            return ServerImportResult.Failed(targetName, $"已存在同名的伺服器：{targetName}");
        }

        bool isZip = SafeFileSystem.FileExists(sourceDirectory) && sourceDirectory.EndsWith(".zip", StringComparison.OrdinalIgnoreCase);
        string targetDir = Path.Combine(_serversRoot, targetName);
        string stagingDir = Path.Combine(_serversRoot, $".import-staging-{Guid.NewGuid():N}");
        bool completedSuccessfully = false;

        progress?.Report(new ServerImportProgressReport(5, "正在準備暫存環境..."));

        try
        {
            SafeFileSystem.CreateDirectory(stagingDir);

            if (isZip)
            {
                progress?.Report(new ServerImportProgressReport(10, "正在解壓縮伺服器封存檔..."));
                await Task.Run(() =>
                {
                    SafeZipArchive.Extract(sourceDirectory, stagingDir, (extracted, total) =>
                    {
                        int pct = total > 0 ? (int)(10 + (extracted * 45 / total)) : 35;
                        progress?.Report(new ServerImportProgressReport(Math.Clamp(pct, 10, 55), $"正在解壓縮檔案 ({Math.Clamp(pct, 10, 55)}%)..."));
                    });
                }, cancellationToken).ConfigureAwait(false);
            }
            else
            {
                progress?.Report(new ServerImportProgressReport(20, "正在複製伺服器檔案..."));
                string stableSource = SafeFileSystem.ResolveStableDirectory(sourceDirectory);
                await Task.Run(() => SafeFileSystem.CopyDirectoryTreeSafe(stableSource, stagingDir), cancellationToken).ConfigureAwait(false);
            }

            string stableStaging = SafeFileSystem.ResolveStableDirectory(stagingDir);

            progress?.Report(new ServerImportProgressReport(60, "正在正規化伺服器檔案結構..."));
            FlattenSingleWrapper(stableStaging);

            progress?.Report(new ServerImportProgressReport(70, "正在分析 Minecraft 核心與載入器..."));
            var inspection = await _inspector.InspectAsync(stableStaging, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (!inspection.IsCandidate)
            {
                Logger.Warning("來源目錄不包含有效的 Minecraft 伺服器檔案: {Source}", sourceDirectory);
                return ServerImportResult.Failed(targetName, "來源目錄不包含有效的 Minecraft 伺服器檔案 (未找到伺服器核心 jar 或關鍵執行檔案)");
            }

            progress?.Report(new ServerImportProgressReport(80, "正在設定伺服器環境與屬性..."));

            // 確保 eula.txt 存在
            string eulaFile = Path.Combine(stableStaging, "eula.txt");
            if (!SafeFileSystem.FileExists(eulaFile))
            {
                AtomicFileWriter.WriteText(eulaFile, "eula=true\n");
            }

            // 自動遷移舊版 server.properties 屬性
            string propsPath = Path.Combine(stableStaging, "server.properties");
            if (SafeFileSystem.FileExists(propsPath))
            {
                try
                {
                    string propsContent = await SafeFileSystem.ReadAllTextAsync(propsPath, Encoding.UTF8, cancellationToken: cancellationToken).ConfigureAwait(false);
                    var rawProps = PropertiesDocumentCodec.Parse(propsContent);
                    var migrationPlan = ServerPropertiesMigrationService.PlanMigration(rawProps, inspection.MinecraftVersion);
                    if (migrationPlan.NeedsMigration)
                    {
                        ServerPropertiesMigrationService.ApplyMigrationToDirectory(stableStaging, migrationPlan, createBackup: true);
                        Logger.Information("伺服器「{Name}」匯入時已自動遷移 server.properties 設定", targetName);
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("伺服器匯入屬性遷移略過: {Message}", ex.Message);
                }
            }

            progress?.Report(new ServerImportProgressReport(85, "正在維護受管啟動腳本..."));
            string launchTarget = !string.IsNullOrWhiteSpace(inspection.LaunchTarget.Value)
                ? inspection.LaunchTarget.Value
                : (DetectLaunchJar(stableStaging) ?? "server.jar");

            string existingBat = Path.Combine(stableStaging, "start_server.bat");
            if (SafeFileSystem.FileExists(existingBat))
            {
                try
                {
                    string backupBat = Path.Combine(stableStaging, "start_server.bat.bak");
                    SafeFileSystem.CopyFile(existingBat, backupBat, overwrite: true);
                }
                catch
                {
                }
            }

            var loaderKind = Enum.TryParse<LoaderKind>(inspection.LoaderType, ignoreCase: true, out var lk) ? lk : LoaderKind.Vanilla;
            int memMax = inspection.MemoryMaxMb > 0 ? inspection.MemoryMaxMb : 2048;
            int memMin = inspection.MemoryMinMb is > 0 ? inspection.MemoryMinMb.Value : 1024;
            string? importJavaPath = await ResolveJavaExecutableAsync(null, inspection.MinecraftVersion, loaderKind, cancellationToken).ConfigureAwait(false);
            WriteStartScript(stableStaging, launchTarget, memMax, memMin, importJavaPath, null);
            CleanupRedundantStartupScripts(stableStaging);

            progress?.Report(new ServerImportProgressReport(90, "正在移入伺服器主資料夾..."));

            // 將 staging 移至 targetDir
            SafeFileSystem.ResolveStableDirectory(targetDir, create: true);
            var stagingEntries = SafeFileSystem.ListBoundedDirectory(stableStaging, rejectReparse: false);
            foreach (var entry in stagingEntries)
            {
                string dest = Path.Combine(targetDir, Path.GetFileName(entry.FullPath));
                if (entry.IsDirectory)
                {
                    SafeFileSystem.MovePath(entry.FullPath, dest);
                }
                else
                {
                    SafeFileSystem.MovePath(entry.FullPath, dest);
                }
            }

            var mcVersion = MinecraftVersion.TryParse(inspection.MinecraftVersion, out var mv) ? mv : MinecraftVersion.Parse("1.20.4");

            var config = new ServerConfig(
                name: serverName,
                minecraftVersion: mcVersion,
                loaderType: loaderKind,
                loaderVersion: inspection.LoaderVersion,
                memoryMaxMb: inspection.MemoryMaxMb,
                memoryMinMb: inspection.MemoryMinMb,
                path: targetDir);

            lock (_lock)
            {
                var registry = LoadRegistry();
                registry[targetName] = ServerConfigPayload.FromDomain(config);
                SaveRegistry(registry);
            }

            progress?.Report(new ServerImportProgressReport(100, "伺服器匯入完成！"));

            completedSuccessfully = true;
            Logger.Information("伺服器「{Name}」匯入成功！目標路徑: {Path}, MC: {MC}, Loader: {Loader}", targetName, targetDir, mcVersion.Value, loaderKind);
            return ServerImportResult.Success(targetName, config);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "匯入伺服器「{Name}」失敗: {Message}", targetName, ex.Message);
            if (!completedSuccessfully && SafeFileSystem.DirectoryExists(targetDir))
            {
                try
                {
                    SafeFileSystem.DeleteWithin(_serversRoot, targetDir);
                }
                catch
                {
                }
            }
            return ServerImportResult.Failed(targetName, $"匯入伺服器失敗：{ex.Message}");
        }
        finally
        {
            if (SafeFileSystem.DirectoryExists(stagingDir))
            {
                try
                {
                    SafeFileSystem.DeleteWithin(_serversRoot, stagingDir);
                }
                catch
                {
                }
            }
        }
    }

    /// <summary>
    /// 掃描 servers 根目錄一級子目錄，分類為「已管理 / 新增 / 跳過」並自動註冊新增項目。
    /// </summary>
    public async Task<ServerScanReport> ScanAndRegisterAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        int alreadyManaged = 0;
        int newlyAdded = 0;
        int skipped = 0;
        var newNames = new List<string>();
        var newConfigs = new List<(string Name, ServerConfig Config)>();

        Dictionary<string, ServerConfigPayload> snapshot;
        lock (_lock)
        {
            snapshot = LoadRegistry();
        }

        var registeredPaths = snapshot.Values
            .Select(static p => p.Path)
            .Where(static p => !string.IsNullOrWhiteSpace(p))
            .Select(static p => Path.GetFullPath(p).TrimEnd(Path.DirectorySeparatorChar))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        foreach (string directory in SafeFileSystem.EnumerateDirectories(_serversRoot))
        {
            cancellationToken.ThrowIfCancellationRequested();

            string folderName = Path.GetFileName(directory);

            // 略過暫存、墓碑與隱藏目錄
            if (folderName.StartsWith('.'))
            {
                continue;
            }

            string fullPath = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar);
            if (registeredPaths.Contains(fullPath) || snapshot.ContainsKey(folderName))
            {
                alreadyManaged++;
                continue;
            }

            ServerInspection inspection;
            try
            {
                inspection = await _inspector.InspectAsync(directory, cancellationToken: cancellationToken).ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                Logger.Warning("偵測目錄「{Path}」失敗，已跳過：{Message}", directory, exception.Message);
                skipped++;
                continue;
            }

            if (!inspection.IsCandidate)
            {
                skipped++;
                continue;
            }

            if (!ServerName.TryParse(folderName, out var serverName))
            {
                Logger.Warning("目錄名稱「{Name}」不符伺服器命名規則，已跳過", folderName);
                skipped++;
                continue;
            }

            var loaderKind = Enum.TryParse<LoaderKind>(inspection.LoaderType, ignoreCase: true, out var lk) ? lk : LoaderKind.Vanilla;
            var mcVersion = MinecraftVersion.TryParse(inspection.MinecraftVersion, out var mv) ? mv : MinecraftVersion.Parse("1.20.4");

            var config = new ServerConfig(
                name: serverName,
                minecraftVersion: mcVersion,
                loaderType: loaderKind,
                loaderVersion: inspection.LoaderVersion,
                memoryMaxMb: inspection.MemoryMaxMb,
                memoryMinMb: inspection.MemoryMinMb,
                path: directory);

            newConfigs.Add((folderName, config));
            newlyAdded++;
            newNames.Add(folderName);
            Logger.Information("偵測並預備註冊新伺服器「{Name}」：MC {MC} / {Loader}", folderName, mcVersion.Value, loaderKind);
        }

        if (newConfigs.Count > 0)
        {
            lock (_lock)
            {
                var registry = LoadRegistry();
                foreach (var (folderName, config) in newConfigs)
                {
                    registry[folderName] = ServerConfigPayload.FromDomain(config);
                }
                SaveRegistry(registry);
            }
        }

        Logger.Information("伺服器偵測完成：已管理 {Managed}，新增 {Added}，跳過 {Skipped}", alreadyManaged, newlyAdded, skipped);
        return new ServerScanReport(alreadyManaged, newlyAdded, skipped, newNames);
    }

    private Dictionary<string, ServerConfigPayload> LoadRegistry()
    {
        if (!SafeFileSystem.FileExists(_registryFilePath))
        {
            _cachedRegistry = new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
            return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
        }

        try
        {
            DateTime lastWrite = SafeFileSystem.GetFileLastWriteTimeUtc(_registryFilePath);
            if (_cachedRegistry is not null && lastWrite == _lastRegistryWriteTimeUtc)
            {
                return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
            }

            string json = SafeFileSystem.ReadAllText(_registryFilePath, Encoding.UTF8);
            var loaded = JsonCodec.Deserialize<Dictionary<string, ServerConfigPayload>>(json)
                   ?? new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
            _cachedRegistry = new Dictionary<string, ServerConfigPayload>(loaded, StringComparer.OrdinalIgnoreCase);
            _lastRegistryWriteTimeUtc = lastWrite;
            return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
        }
        catch
        {
            return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
        }
    }

    private void SaveRegistry(Dictionary<string, ServerConfigPayload> registry)
    {
        string json = JsonCodec.Serialize(registry, indented: true);
        AtomicFileWriter.WriteText(_registryFilePath, json);
        _cachedRegistry = new Dictionary<string, ServerConfigPayload>(registry, StringComparer.OrdinalIgnoreCase);
        if (SafeFileSystem.FileExists(_registryFilePath))
        {
            _lastRegistryWriteTimeUtc = SafeFileSystem.GetFileLastWriteTimeUtc(_registryFilePath);
        }
    }


    private static void FlattenSingleWrapper(string stagingDir)
    {
        for (int i = 0; i < 3; i++)
        {
            var entries = SafeFileSystem.ListBoundedDirectory(stagingDir, rejectReparse: false);
            if (entries.Count == 1 && entries[0].IsDirectory)
            {
                string wrapperPath = entries[0].FullPath;
                var childEntries = SafeFileSystem.ListBoundedDirectory(wrapperPath, rejectReparse: false);
                if (childEntries.Count == 0)
                {
                    break;
                }

                foreach (var child in childEntries)
                {
                    string destination = Path.Combine(stagingDir, Path.GetFileName(child.FullPath));
                    if (child.IsDirectory)
                    {
                        SafeFileSystem.MovePath(child.FullPath, destination);
                    }
                    else
                    {
                        SafeFileSystem.MovePath(child.FullPath, destination);
                    }
                }

                SafeFileSystem.DeleteDirectory(wrapperPath, recursive: true);
            }
            else
            {
                break;
            }
        }
    }
}

internal sealed record ServerConfigPayload(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("minecraftVersion")] string MinecraftVersion,
    [property: JsonPropertyName("loaderType")] string LoaderType,
    [property: JsonPropertyName("loaderVersion")] string LoaderVersion,
    [property: JsonPropertyName("memoryMaxMb")] int MemoryMaxMb,
    [property: JsonPropertyName("memoryMinMb")] int? MemoryMinMb,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("jvmArgs")] IReadOnlyList<string> JvmArgs,
    [property: JsonPropertyName("backupPath")] string BackupPath)
{
    public static ServerConfigPayload FromDomain(ServerConfig config) => new(
        Name: config.Name.Value,
        MinecraftVersion: config.MinecraftVersion.Value,
        LoaderType: config.LoaderType.ToString(),
        LoaderVersion: config.LoaderVersion,
        MemoryMaxMb: config.MemoryMaxMb,
        MemoryMinMb: config.MemoryMinMb,
        Path: config.Path,
        JvmArgs: config.JvmArgs,
        BackupPath: config.BackupPath);
}
