using System.Collections.Frozen;
using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器集中管理服務實作
/// </summary>
public sealed partial class ServerManager : IServerManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerManager));
    private readonly string _serversRoot;
    private readonly string _registryFilePath;
    private readonly IServerInspector _inspector;
    private readonly ILoaderInstallerService _loaderInstaller;
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IMinecraftJavaRequirementService _javaRequirementService;
    private readonly Lock _lock = new();
    private Dictionary<string, ServerConfigPayload>? _cachedRegistry;
    private DateTime _lastRegistryWriteTimeUtc;
    private bool _unreadableRegistryPreserved;

    public ServerManager(
        string serversRoot,
        IServerInspector inspector,
        ILoaderInstallerService loaderInstaller,
        IJavaRuntimeDetector javaDetector,
        IMinecraftJavaRequirementService javaRequirementService)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        ArgumentNullException.ThrowIfNull(inspector);
        ArgumentNullException.ThrowIfNull(loaderInstaller);
        ArgumentNullException.ThrowIfNull(javaDetector);
        ArgumentNullException.ThrowIfNull(javaRequirementService);
        _serversRoot = SafeFileSystem.ResolveStableDirectory(serversRoot, create: true);
        _registryFilePath = Path.Combine(_serversRoot, ServerDefaults.RegistryFileName);
        _inspector = inspector;
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
                if (TryCreateServerConfig(payload, _serversRoot, out var config))
                {
                    result.Add(config!);
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
            return registry.TryGetValue(name, out var payload) && TryCreateServerConfig(payload, _serversRoot, out var config)
                ? Task.FromResult(config)
                : Task.FromResult<ServerConfig?>(null);
        }
    }

    private static bool TryCreateServerConfig(ServerConfigPayload payload, string serversRoot, out ServerConfig? config)
    {
        if (ServerName.TryParse(payload.Name, out var name)
            && MinecraftVersion.TryParse(payload.MinecraftVersion, out var mcVer)
            && LoaderKinds.TryParse(payload.LoaderType, out var loader))
        {
            config = new ServerConfig(
                name: name,
                minecraftVersion: mcVer,
                loaderType: loader,
                loaderVersion: payload.LoaderVersion ?? string.Empty,
                memoryMaxMb: payload.MemoryMaxMb > 0 ? payload.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb,
                memoryMinMb: payload.MemoryMinMb,
                path: payload.Path ?? Path.Combine(serversRoot, payload.Name),
                jvmArgs: payload.JvmArgs,
                backupPath: payload.BackupPath ?? string.Empty);
            return true;
        }

        config = null;
        return false;
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

        var existing = await GetServerAsync(plan.Config.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            return ServerCreationResult.Failed($"已存在同名的伺服器：{plan.Config.Name.Value}");
        }

        string serverDir = Path.Combine(_serversRoot, plan.Config.Name.Value);
        if (SafeFileSystem.DirectoryExists(serverDir) && !SafeFileSystem.IsDirectoryEmpty(serverDir))
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

        Logger.Information("開始建立伺服器「{Name}」 (MC: {McVer}, 載入器: {Loader} {LoaderVer}, 記憶體: {MemMax}MB)", plan.Config.Name.Value, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, plan.Config.LoaderVersion, plan.Config.MemoryMaxMb);

        try
        {
            // ── Phase 2: Stage (5% ~ 15%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 5, "正在建立暫存目錄與初始設定檔..."));

            string stableStaging = SafeFileSystem.ResolveStableDirectory(stagingDir, create: true);
            createdDir = true;

            // 寫入 eula.txt
            string eulaPath = Path.Combine(stableStaging, ServerDefaults.EulaFileName);
            AtomicFileWriter.WriteText(eulaPath, "eula=true\n");

            // 寫入初始 server.properties（含 MOTD 與 Port）
            string propertiesPath = Path.Combine(stableStaging, ServerDefaults.ServerPropertiesFileName);
            var initialProps = new Dictionary<string, string>(ServerPropertiesMetadata.DefaultProperties)
            {
                ["motd"] = $"A Minecraft Server ({plan.Config.Name.Value})",
                ["server-port"] = ServerDefaults.DefaultPort,
            };

            string propsText = PropertiesDocumentCodec.Serialize(initialProps);
            AtomicFileWriter.WriteText(propertiesPath, propsText);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 15, "初始設定檔已建立"));

            // ── Phase 3: Artifact (15% ~ 85%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 15, "正在下載伺服器核心..."));

            string? resolvedJavaPath = await ResolveJavaExecutableAsync(plan.UserJavaPath, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, cancellationToken).ConfigureAwait(false);

            int lastArtifactPct = 15;
            Lock artifactProgressLock = new();
            var loaderProgress = progress is null ? null : new SynchronousProgress<LoaderInstallProgress>(lp =>
            {
                int mappedPct = 15 + (int)(lp.PercentCompleted * 0.70); // 15% ~ 85%
                int clamped = Math.Clamp(mappedPct, 15, 85);
                lock (artifactProgressLock)
                {
                    clamped = Math.Max(lastArtifactPct, clamped);
                    lastArtifactPct = clamped;
                }
                progress.Report(new ServerCreationProgressReport(
                    ServerCreationPhase.Artifact, clamped, lp.Message));
            });

            await _loaderInstaller.InstallLoaderAsync(
                loader: plan.Config.LoaderType,
                minecraftVersion: plan.Config.MinecraftVersion.Value,
                loaderVersion: plan.Config.LoaderVersion,
                serverDirectory: stableStaging,
                javaExecutablePath: resolvedJavaPath ?? "java",
                progress: loaderProgress,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 85, "伺服器核心安裝完成"));

            // ── Phase 4: LaunchScript (85% ~ 95%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.LaunchScript, 85, "正在生成啟動腳本..."));

            string? launchJar = ServerLaunchTargetResolver.ResolveLaunchTarget(stableStaging, plan.Config.LoaderType);
            if (launchJar is null)
            {
                return ServerCreationResult.Failed("找不到可用的啟器 JAR 或參數設定檔，伺服器核心可能下載失敗");
            }

            StartScriptWriter.Write(stableStaging, launchJar, plan.Config.MemoryMaxMb, plan.Config.MemoryMinMb ?? ServerDefaults.DefaultMemoryMinMb, resolvedJavaPath, plan.Config.JvmArgs, plan.Config.LoaderType);
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

            var config = plan.Config.WithPath(serverDir);
            if (StartScriptWriter.UsesUserJvmArgsFile(plan.Config.LoaderType, serverDir))
            {
                StartScriptWriter.UpdateUserJvmArgs(serverDir, config);
            }

            SetRegistryEntry(plan.Config.Name.Value, config);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Commit, 100, "伺服器建立完成！"));
            Logger.Information("伺服器「{Name}」建立成功！路徑: {Path}", plan.Config.Name.Value, serverDir);
            return ServerCreationResult.Success(config);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器「{Name}」失敗: {Message}", plan.Config.Name.Value, ex.Message);
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
                    catch (Exception cleanEx) when (cleanEx is not OperationCanceledException)
                    {
                        Logger.Warning(cleanEx, "建立伺服器失敗後清理目錄異常: {0}", cleanupTarget);
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
            catch (Exception cleanEx) when (cleanEx is not OperationCanceledException)
            {
                Logger.Warning("清理暫存目錄異常: {0}", cleanEx.Message);
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
            return $"磁碟 {root} 可用空間不足（需要至少 {UnitFormatter.FormatBytes(requiredBytes)}）";
        }

        return null;
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
        try
        {
            int targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion, loader, cancellationToken).ConfigureAwait(false);
            var match = await _javaDetector.FindBestMatchAsync(targetMajor, cancellationToken).ConfigureAwait(false);
            if (match is not null && SafeFileSystem.FileExists(match.ExecutablePath))
            {
                return match.ExecutablePath;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("依 Minecraft {Version} 與載入器 {Loader} 尋找 Java 失敗: {Message}", minecraftVersion, loader, ex.Message);
        }

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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("自動偵測 Java 執行檔異常: {0}", ex.Message);
        }

        // 搜尋系統 PATH 中的 java.exe 完整絕對路徑
        string? sysJava = JavaRuntimeDetector.FindSystemJavaExecutable();
        if (!string.IsNullOrWhiteSpace(sysJava) && SafeFileSystem.FileExists(sysJava))
        {
            return sysJava;
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
                    if (string.Equals(fileName, ServerDefaults.StartServerBatFileName, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(fileName, ServerDefaults.StartServerBatFileName + ".bak", StringComparison.OrdinalIgnoreCase))
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

    public async Task<ServerOperationResult> DeleteServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        cancellationToken.ThrowIfCancellationRequested();

        var config = await GetServerAsync(name, cancellationToken).ConfigureAwait(false);
        if (config is null)
        {
            return ServerOperationResult.Fail($"找不到伺服器：{name}");
        }

        // 以註冊表記錄的實際路徑為準（存放目錄遷移後與 servers 根目錄 + 名稱可能不同）；邊界由 tombstone 搬移時強制驗證
        string serverDir = config.Path;

        Logger.Information("開始刪除伺服器「{Name}」...", name);

        try
        {
            // 兩階段安全刪除
            string? tombstonePath = null;
            string? journalPath = null;
            if (SafeFileSystem.DirectoryExists(serverDir))
            {
                (tombstonePath, journalPath) = ServerTombstoneManager.PrepareDeleteTombstone(_serversRoot, name, serverDir);
            }

            RemoveRegistryEntry(name);

            if (tombstonePath is not null && journalPath is not null)
            {
                ServerTombstoneManager.CleanTombstone(_serversRoot, tombstonePath, journalPath);
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

        SetRegistryEntry(config.Name.Value, config);

        if (SafeFileSystem.DirectoryExists(config.Path))
        {
            if (StartScriptWriter.UsesUserJvmArgsFile(config.LoaderType, config.Path))
            {
                StartScriptWriter.UpdateUserJvmArgs(config.Path, config);
            }

            StartScriptWriter.UpdateMemory(config.Path, config);
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
            string eulaFile = Path.Combine(stableStaging, ServerDefaults.EulaFileName);
            if (!SafeFileSystem.FileExists(eulaFile))
            {
                AtomicFileWriter.WriteText(eulaFile, "eula=true\n");
            }

            // 自動遷移舊版 server.properties 屬性
            string propsPath = Path.Combine(stableStaging, ServerDefaults.ServerPropertiesFileName);
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
            var loaderKind = LoaderKinds.ParseOrDefault(inspection.LoaderType, LoaderKind.Vanilla);
            string launchTarget = !string.IsNullOrWhiteSpace(inspection.LaunchTarget.Value)
                ? inspection.LaunchTarget.Value
                : ServerLaunchTargetResolver.ResolveLaunchTarget(stableStaging, loaderKind);

            string existingBat = Path.Combine(stableStaging, ServerDefaults.StartServerBatFileName);
            if (SafeFileSystem.FileExists(existingBat))
            {
                try
                {
                    string backupBat = Path.Combine(stableStaging, ServerDefaults.StartServerBatFileName + ".bak");
                    SafeFileSystem.CopyFile(existingBat, backupBat, overwrite: true);
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Warning("備份現有啟動腳本異常: {0}", ex.Message);
                }
            }

            int memMax = inspection.MemoryMaxMb > 0 ? inspection.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb;
            int memMin = inspection.MemoryMinMb is > 0 ? inspection.MemoryMinMb.Value : ServerDefaults.DefaultMemoryMinMb;
            string? importJavaPath = await ResolveJavaExecutableAsync(null, inspection.MinecraftVersion, loaderKind, cancellationToken).ConfigureAwait(false);
            StartScriptWriter.Write(stableStaging, launchTarget, memMax, memMin, importJavaPath, null, loaderKind);
            CleanupRedundantStartupScripts(stableStaging);

            progress?.Report(new ServerImportProgressReport(90, "正在移入伺服器主資料夾..."));

            // 將 staging 移至 targetDir
            SafeFileSystem.ResolveStableDirectory(targetDir, create: true);
            var stagingEntries = SafeFileSystem.ListBoundedDirectory(stableStaging, rejectReparse: false);
            foreach (var entry in stagingEntries)
            {
                string dest = Path.Combine(targetDir, Path.GetFileName(entry.FullPath));
                SafeFileSystem.MovePath(entry.FullPath, dest);
            }

            var config = CreateConfigFromInspection(serverName, loaderKind, inspection, targetDir);

            SetRegistryEntry(targetName, config);

            completedSuccessfully = true;

            if (mode == ImportTransferMode.Move)
            {
                progress?.Report(new ServerImportProgressReport(96, "正在移除原始來源檔案..."));
                try
                {
                    if (isZip)
                    {
                        SafeFileSystem.DeleteFile(sourceDirectory);
                    }
                    else if (SafeFileSystem.DirectoryExists(sourceDirectory))
                    {
                        SafeFileSystem.DeleteDirectory(sourceDirectory, recursive: true);
                    }
                    Logger.Information("伺服器「{Name}」以遷移模式匯入，已移除原始來源: {Source}", targetName, sourceDirectory);
                }
                catch (Exception moveCleanEx) when (moveCleanEx is not OperationCanceledException)
                {
                    Logger.Warning(moveCleanEx, "遷移匯入完成後移除原始來源失敗: {0}", sourceDirectory);
                }
            }

            progress?.Report(new ServerImportProgressReport(100, "伺服器匯入完成！"));
            Logger.Information("伺服器「{Name}」匯入成功！目標路徑: {Path}, MC: {MC}, Loader: {Loader}", targetName, targetDir, config.MinecraftVersion.Value, loaderKind);
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
                catch (Exception cleanEx) when (cleanEx is not OperationCanceledException)
                {
                    Logger.Warning(cleanEx, "匯入失敗後清理目標目錄異常: {0}", targetDir);
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
                catch (Exception cleanEx) when (cleanEx is not OperationCanceledException)
                {
                    Logger.Warning("清理匯入暫存目錄異常: {0}", cleanEx.Message);
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
            .Select(static p => Path.TrimEndingDirectorySeparator(Path.GetFullPath(p)))
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

            string fullPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
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

            var loaderKind = LoaderKinds.ParseOrDefault(inspection.LoaderType, LoaderKind.Vanilla);
            var config = CreateConfigFromInspection(serverName, loaderKind, inspection, directory);

            newConfigs.Add((folderName, config));
            newlyAdded++;
            newNames.Add(folderName);
            Logger.Information("偵測並預備註冊新伺服器「{Name}」：MC {MC} / {Loader}", folderName, config.MinecraftVersion.Value, loaderKind);
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

    /// <summary>
    /// 依偵測結果建立伺服器設定；無法辨識 Minecraft 版本時沿用預設 1.20.4
    /// </summary>
    private static ServerConfig CreateConfigFromInspection(ServerName name, LoaderKind loader, ServerInspection inspection, string path) => new(
        name: name,
        minecraftVersion: MinecraftVersion.TryParse(inspection.MinecraftVersion, out var version) ? version : MinecraftVersion.Parse("1.20.4"),
        loaderType: loader,
        loaderVersion: inspection.LoaderVersion,
        memoryMaxMb: inspection.MemoryMaxMb,
        memoryMinMb: inspection.MemoryMinMb,
        path: path);

    private void SetRegistryEntry(string key, ServerConfig config)
    {
        lock (_lock)
        {
            var registry = LoadRegistry();
            registry[key] = ServerConfigPayload.FromDomain(config);
            SaveRegistry(registry);
        }
    }

    private void RemoveRegistryEntry(string key)
    {
        lock (_lock)
        {
            var registry = LoadRegistry();
            registry.Remove(key);
            SaveRegistry(registry);
        }
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
            var loaded = JsonCodec.Deserialize<Dictionary<string, ServerConfigPayload>>(json);
            if (loaded is null)
            {
                // 內容無法解析（損毀或空白）：保留原檔後以空白清單繼續，避免下次儲存永久覆蓋
                Logger.Warning("伺服器註冊表內容無法解析，使用空白清單: {Path}", _registryFilePath);
                PreserveUnreadableRegistry();
                return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
            }

            _cachedRegistry = new Dictionary<string, ServerConfigPayload>(loaded, StringComparer.OrdinalIgnoreCase);
            _lastRegistryWriteTimeUtc = lastWrite;
            return new Dictionary<string, ServerConfigPayload>(_cachedRegistry, StringComparer.OrdinalIgnoreCase);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "讀取伺服器註冊表失敗，使用空白清單: {Path}", _registryFilePath);
            PreserveUnreadableRegistry();
            return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
        }
    }

    /// <summary>
    /// 註冊表無法讀取時保留原檔為 <c>.bad</c>，避免下次儲存以空白清單覆寫而永久遺失
    /// </summary>
    private void PreserveUnreadableRegistry()
    {
        if (_unreadableRegistryPreserved)
        {
            return;
        }

        try
        {
            SafeFileSystem.CopyFile(_registryFilePath, _registryFilePath + ".bad", overwrite: true);
            _unreadableRegistryPreserved = true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "無法備份損毀的伺服器註冊表: {Path}", _registryFilePath);
        }
    }

    private void SaveRegistry(Dictionary<string, ServerConfigPayload> registry)
    {
        _unreadableRegistryPreserved = false;
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
                    SafeFileSystem.MovePath(child.FullPath, destination);
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
