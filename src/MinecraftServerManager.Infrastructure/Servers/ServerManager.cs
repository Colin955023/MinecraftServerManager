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

/// <summary>伺服器集中管理服務實作</summary>
public sealed partial class ServerManager : IServerManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerManager));
    private readonly string _serversRoot;
    private readonly ServerRegistryStore _registry;
    private readonly ServerImportWorkflow _importWorkflow;
    private readonly Lazy<Task> _recovery;
    private readonly IServerInspector _inspector;
    private readonly ILoaderInstallerService _loaderInstaller;
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IMinecraftJavaRequirementService _javaRequirementService;

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
        _registry = new ServerRegistryStore(_serversRoot);
        _inspector = inspector;
        _loaderInstaller = loaderInstaller;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;

        _importWorkflow = new ServerImportWorkflow(_serversRoot, _registry, _inspector, ResolveJavaExecutableAsync);

        // 墓碑復原延後至首次存取時於背景執行，避免阻塞建構（UI 執行緒）
        _recovery = new Lazy<Task>(() => Task.Run(() => ServerTombstoneManager.RecoverDeleteTombstones(_serversRoot, _registry.FindPath)));
    }

    private Task EnsureRecoveredAsync() => _recovery.Value;

    public async Task<IReadOnlyList<ServerConfig>> GetAllServersAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureRecoveredAsync().ConfigureAwait(false);
        return await Task.Run(_registry.GetAll, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ServerConfig?> GetServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureRecoveredAsync().ConfigureAwait(false);
        return await Task.Run(() => _registry.Find(name), cancellationToken).ConfigureAwait(false);
    }

    public async Task<ServerCreationResult> CreateServerAsync(
        ServerCreationPlan plan,
        IProgress<ServerCreationProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(plan);
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureRecoveredAsync().ConfigureAwait(false);

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

        string? insufficientSpace = ServerSetupHelpers.CheckFreeSpace(_serversRoot, 500L * 1024 * 1024);
        if (insufficientSpace is not null)
        {
            return ServerCreationResult.Failed(insufficientSpace);
        }

        bool createdDir = false;
        string stagingDir = Path.Combine(_serversRoot, $"{ServerDefaults.InternalPrefix}create-staging-{Guid.NewGuid():N}");

        Logger.Information("開始建立伺服器「{Name}」 (MC: {McVer}, 載入器: {Loader} {LoaderVer}, 記憶體: {MemMax}MB)", plan.Config.Name.Value, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, plan.Config.LoaderVersion, plan.Config.MemoryMaxMb);

        try
        {
            // ── Phase 2: Stage (5% ~ 15%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 5, "正在建立暫存目錄與初始設定檔..."));

            string stableStaging = SafeFileSystem.ResolveStableDirectory(stagingDir, create: true);
            createdDir = true;

            // 寫入 eula.txt
            string eulaPath = Path.Combine(stableStaging, ServerDefaults.EulaFileName);
            AtomicFileWriter.WriteTextOrThrow(eulaPath, "eula=true\n");

            // 寫入初始 server.properties（含 MOTD 與 Port）
            string propertiesPath = Path.Combine(stableStaging, ServerDefaults.ServerPropertiesFileName);
            var initialProps = new Dictionary<string, string>(ServerPropertiesMetadata.DefaultProperties)
            {
                ["motd"] = $"A Minecraft Server ({plan.Config.Name.Value})",
                ["server-port"] = ServerDefaults.DefaultPort,
            };

            string propsText = PropertiesDocumentCodec.Serialize(initialProps);
            AtomicFileWriter.WriteTextOrThrow(propertiesPath, propsText);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 15, "初始設定檔已建立"));

            // ── Phase 3: Artifact (15% ~ 85%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 15, "正在下載伺服器核心..."));

            string? resolvedJavaPath = await ResolveJavaExecutableAsync(plan.UserJavaPath, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, cancellationToken).ConfigureAwait(false);
            if (resolvedJavaPath is null)
            {
                return ServerCreationResult.Failed($"本機找不到與 Minecraft {plan.Config.MinecraftVersion.Value} 官方指定 major 完全一致的 Java，已阻擋建立；請先安裝所需的 Java 版本");
            }

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
                javaExecutablePath: resolvedJavaPath,
                progress: loaderProgress,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 85, "伺服器核心安裝完成"));

            // ── Phase 4: LaunchScript (85% ~ 95%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.LaunchScript, 85, "正在生成啟動腳本..."));

            string? launchJar = ServerLaunchTargetResolver.ResolveLaunchTarget(stableStaging, plan.Config.LoaderType);
            if (launchJar is null)
            {
                return ServerCreationResult.Failed("找不到可用的啟動 JAR 或參數設定檔，伺服器核心可能下載失敗");
            }

            StartScriptWriter.Write(stableStaging, launchJar, plan.Config.MemoryMaxMb, plan.Config.MemoryMinMb ?? ServerDefaults.DefaultMemoryMinMb, resolvedJavaPath, plan.Config.JvmArgs, plan.Config.LoaderType);
            ServerSetupHelpers.CleanupRedundantStartupScripts(stableStaging);
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

            _registry.Set(plan.Config.Name.Value, config);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Commit, 100, "伺服器建立完成！"));
            Logger.Information("伺服器「{Name}」建立成功！路徑: {Path}", plan.Config.Name.Value, serverDir);
            return ServerCreationResult.Success(config);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("使用者已取消建立伺服器「{Name}」", plan.Config.Name.Value);
            if (createdDir)
            {
                CleanupCreationDirectories(stagingDir, serverDir);
            }

            return ServerCreationResult.Failed("已取消建立伺服器");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器「{Name}」失敗", plan.Config.Name.Value);
            if (createdDir)
            {
                CleanupCreationDirectories(stagingDir, serverDir);
            }
            return ServerCreationResult.Failed($"建立伺服器時發生例外：{ex.Message}");
        }
        finally
        {
            // 清理殘留暫存目錄（DeleteWithin 對不存在的路徑與失敗皆自行處理並記錄）
            if (createdDir)
            {
                SafeFileSystem.DeleteWithin(_serversRoot, stagingDir);
            }
        }
    }

    private void CleanupCreationDirectories(string stagingDir, string serverDir)
    {
        SafeFileSystem.DeleteWithin(_serversRoot, stagingDir);
        SafeFileSystem.DeleteWithin(_serversRoot, serverDir);
    }

    /// <summary>解析符合官方指定 Java major 的執行檔；major 必須完全一致，無法確認或找不到時回傳 null（不退而求其次）。</summary>
    private async Task<string?> ResolveJavaExecutableAsync(
        string? configuredJava,
        string minecraftVersion,
        LoaderKind loader = LoaderKind.Unknown,
        CancellationToken cancellationToken = default)
    {
        try
        {
            int targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion, loader, cancellationToken).ConfigureAwait(false);

            if (!string.IsNullOrWhiteSpace(configuredJava) && !string.Equals(configuredJava.Trim(), "java", StringComparison.OrdinalIgnoreCase))
            {
                string trimmed = configuredJava.Trim();
                var detected = await _javaDetector.DetectAsync(forceRefresh: false, cancellationToken: cancellationToken).ConfigureAwait(false);
                if (detected.Any(j => j.MajorVersion == targetMajor &&
                                      string.Equals(j.ExecutablePath, trimmed, StringComparison.OrdinalIgnoreCase)) &&
                    SafeFileSystem.FileExists(trimmed))
                {
                    return trimmed;
                }
            }

            var match = await _javaDetector.FindBestMatchAsync(targetMajor, cancellationToken).ConfigureAwait(false);
            if (match is not null && match.MajorVersion == targetMajor && SafeFileSystem.FileExists(match.ExecutablePath))
            {
                return match.ExecutablePath;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "依 Minecraft {Version} 與載入器 {Loader} 尋找符合官方指定 major 的 Java 失敗", minecraftVersion, loader);
        }

        return null;
    }

    public async Task<ServerOperationResult> DeleteServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureRecoveredAsync().ConfigureAwait(false);

        var config = await GetServerAsync(name, cancellationToken).ConfigureAwait(false);
        if (config is null)
        {
            return ServerOperationResult.Fail($"找不到伺服器：{name}");
        }

        // 以登錄檔記錄的實際路徑為準（存放目錄遷移後與 servers 根目錄 + 名稱可能不同）；邊界由 tombstone 搬移時強制驗證
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

            _registry.Remove(name);

            if (tombstonePath is not null && journalPath is not null)
            {
                ServerTombstoneManager.CleanTombstone(_serversRoot, tombstonePath, journalPath);
            }

            Logger.Information("伺服器「{Name}」已完全刪除並清理完畢", name);
            return ServerOperationResult.Ok($"成功刪除伺服器：{name}");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "刪除伺服器「{Name}」失敗", name);
            return ServerOperationResult.Fail($"刪除伺服器失敗：{ex.Message}");
        }
    }

    public async Task<ServerOperationResult> UpdateServerAsync(ServerConfig config, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(config);
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureRecoveredAsync().ConfigureAwait(false);

        var existing = await GetServerAsync(config.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is null)
        {
            return ServerOperationResult.Fail($"找不到要更新的伺服器：{config.Name.Value}");
        }

        _registry.Set(config.Name.Value, config);

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
        await EnsureRecoveredAsync().ConfigureAwait(false);
        return await _importWorkflow.ImportAsync(sourceDirectory, targetName, mode, progress, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>掃描 servers 根目錄一級子目錄，分類為「已管理 / 新增 / 跳過」並自動註冊新增項目。</summary>
    public async Task<ServerScanReport> ScanAndRegisterAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        int alreadyManaged = 0;
        int newlyAdded = 0;
        int skipped = 0;
        var newConfigs = new List<(string Name, ServerConfig Config)>();

        await EnsureRecoveredAsync().ConfigureAwait(false);
        var snapshot = await Task.Run(_registry.Snapshot, cancellationToken).ConfigureAwait(false);

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
                Logger.Warning(exception, "偵測目錄「{Path}」失敗，已跳過", directory);
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
            var config = ServerSetupHelpers.CreateConfigFromInspection(serverName, loaderKind, inspection, directory);

            newConfigs.Add((folderName, config));
            newlyAdded++;
            Logger.Information("偵測並預備註冊新伺服器「{Name}」：MC {MC} / {Loader}", folderName, config.MinecraftVersion.Value, loaderKind);
        }

        if (newConfigs.Count > 0)
        {
            _registry.Update<object?>(registry =>
            {
                foreach (var (folderName, config) in newConfigs)
                {
                    registry[folderName] = ServerConfigPayload.FromDomain(config);
                }

                return null;
            });
        }

        Logger.Information("伺服器偵測完成：已管理 {Managed}，新增 {Added}，跳過 {Skipped}", alreadyManaged, newlyAdded, skipped);
        return new ServerScanReport(alreadyManaged, newlyAdded, skipped);
    }

}
