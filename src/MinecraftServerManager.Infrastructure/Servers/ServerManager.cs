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
public sealed class ServerManager : IServerManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerManager));
    private readonly string _serversRoot;
    private readonly ServerRegistryStore _registry;
    private readonly ServerImportWorkflow _importWorkflow;
    private readonly Lock _recoveryLock = new();
    private Task? _recovery;
    private readonly KeyedAsyncLock _nameGates = new();
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

    }

    /// <summary>墓碑復原延後至首次存取時於背景執行，避免阻塞建構（UI 執行緒）；失敗時下次存取重試</summary>
    private Task EnsureRecoveredAsync()
    {
        lock (_recoveryLock)
        {
            if (_recovery is null || _recovery.IsFaulted || _recovery.IsCanceled)
            {
                _recovery = Task.Run(() => ServerTombstoneManager.RecoverDeleteTombstones(_serversRoot, _registry.FindPath));
            }

            return _recovery;
        }
    }

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

    private async Task<T> RunWithServerGateAsync<T>(
        string serverName,
        Func<CancellationToken, Task<T>> action,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureRecoveredAsync().ConfigureAwait(false);
        using var gate = await _nameGates.AcquireAsync(serverName, cancellationToken).ConfigureAwait(false);
        return await action(cancellationToken).ConfigureAwait(false);
    }

    public Task<ServerCreationResult> CreateServerAsync(
        ServerCreationPlan plan,
        IProgress<ServerCreationProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(plan);
        return RunWithServerGateAsync(plan.Config.Name.Value, ct => CreateServerCoreAsync(plan, progress, ct), cancellationToken);
    }

    private async Task<ServerCreationResult> CreateServerCoreAsync(
        ServerCreationPlan plan,
        IProgress<ServerCreationProgressReport>? progress,
        CancellationToken cancellationToken)
    {
        // ── Phase 1: Validate (0% ~ 5%) ──
        progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Validate, 0, "正在驗證伺服器名稱與目錄..."));

        var existing = await GetServerAsync(plan.Config.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            return ServerCreationResult.Failed($"已存在同名的伺服器：{plan.Config.Name.Value}");
        }

        string serverDir = Path.Combine(_serversRoot, plan.Config.Name.Value);
        if (ServerSetupHelpers.ValidateEmptyTargetDirectory(serverDir, out bool targetExisted) is { } targetError)
        {
            return ServerCreationResult.Failed(targetError);
        }

        string? insufficientSpace = ServerSetupHelpers.CheckFreeSpace(_serversRoot, 500L * 1024 * 1024);
        if (insufficientSpace is not null)
        {
            return ServerCreationResult.Failed(insufficientSpace);
        }

        Logger.Information("開始建立伺服器「{Name}」 (MC: {McVer}, 載入器: {Loader} {LoaderVer}, 記憶體: {MemMax}MB)", plan.Config.Name.Value, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, plan.Config.LoaderVersion, plan.Config.MemoryMaxMb);

        using EphemeralStagingScope staging = new(_serversRoot, serverDir, targetExisted, "create-staging");
        string stableStaging = staging.StableStaging;

        try
        {
            // ── Phase 2: Stage (5% ~ 15%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Stage, 5, "正在建立暫存目錄與初始設定檔..."));

            staging.EnsureEula();

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

            ResolvedJavaRuntime? resolvedJava = await ResolveJavaExecutableAsync(plan.UserJavaPath, plan.Config.MinecraftVersion.Value, cancellationToken).ConfigureAwait(false);
            if (resolvedJava is null)
            {
                return ServerCreationResult.Failed($"本機找不到與 Minecraft {plan.Config.MinecraftVersion.Value} 官方指定 major 完全一致的 Java，已阻擋建立；請先安裝所需的 Java 版本");
            }

            int lastArtifactPct = 15;
            Lock artifactProgressLock = new();
            var loaderProgress = progress is null ? null : new SynchronousProgress<LoaderInstallProgress>(lp =>
            {
                int clamped = ProgressMapping.Map(lp.PercentCompleted, 100, 15, 85);
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
                javaExecutablePath: resolvedJava.ExecutablePath,
                progress: loaderProgress,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Artifact, 85, "伺服器核心安裝完成"));

            // ── Phase 4: LaunchScript (85% ~ 95%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.LaunchScript, 85, "正在產生啟動腳本..."));

            string? launchJar = ServerLaunchTargetResolver.ResolveLaunchTarget(stableStaging, plan.Config.LoaderType);
            if (launchJar is null)
            {
                return ServerCreationResult.Failed("找不到可用的啟動 JAR 或參數設定檔，伺服器核心可能下載失敗");
            }

            ServerSetupHelpers.FinalizeLaunchScripts(stableStaging, launchJar, plan.Config.MemoryMaxMb, plan.Config.MemoryMinMb, resolvedJava.ExecutablePath, plan.Config.JvmArgs, plan.Config.LoaderType, resolvedJava.MajorVersion);
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.LaunchScript, 95, "啟動腳本已產生並通過完整性驗證"));

            // ── Phase 5: Commit (95% ~ 100%) ──
            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Commit, 95, "正在登錄伺服器設定..."));

            var configForStaging = plan.Config.WithPath(stableStaging);
            if (StartScriptWriter.UsesUserJvmArgsFile(plan.Config.LoaderType, stableStaging))
            {
                StartScriptWriter.UpdateUserJvmArgs(stableStaging, configForStaging);
            }

            if (!staging.TryCommitToTarget())
            {
                return ServerCreationResult.Failed("原子移動暫存目錄至正式伺服器目錄失敗");
            }

            var config = plan.Config.WithPath(serverDir);
            _registry.Set(plan.Config.Name.Value, config);
            staging.Complete();

            progress?.Report(new ServerCreationProgressReport(ServerCreationPhase.Commit, 100, "伺服器建立完成！"));
            Logger.Information("伺服器「{Name}」建立成功！路徑: {Path}", plan.Config.Name.Value, serverDir);
            return ServerCreationResult.Success(config);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("使用者已取消建立伺服器「{Name}」", plan.Config.Name.Value);
            return ServerCreationResult.Failed("已取消建立伺服器");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器「{Name}」失敗", plan.Config.Name.Value);
            return ServerCreationResult.Failed($"建立伺服器時發生例外：{ex.Message}");
        }
    }

    /// <summary>解析符合官方 Java major 的執行檔；找不到回傳 null</summary>
    private async Task<ResolvedJavaRuntime?> ResolveJavaExecutableAsync(
        string? configuredJava,
        string minecraftVersion,
        CancellationToken cancellationToken = default)
    {
        try
        {
            int targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion, cancellationToken).ConfigureAwait(false);

            if (!string.IsNullOrWhiteSpace(configuredJava) && !string.Equals(configuredJava.Trim(), ServerDefaults.DefaultJavaCommand, StringComparison.OrdinalIgnoreCase))
            {
                string trimmed = configuredJava.Trim();
                var detected = await _javaDetector.DetectAsync(forceRefresh: false, cancellationToken: cancellationToken).ConfigureAwait(false);
                if (detected.Any(j => j.MajorVersion == targetMajor &&
                                      string.Equals(j.ExecutablePath, trimmed, StringComparison.OrdinalIgnoreCase)) &&
                    SafeFileSystem.FileExists(trimmed))
                {
                    return new ResolvedJavaRuntime(trimmed, targetMajor);
                }
            }

            var match = await _javaDetector.FindBestMatchAsync(targetMajor, cancellationToken).ConfigureAwait(false);
            if (match is not null && match.MajorVersion == targetMajor && SafeFileSystem.FileExists(match.ExecutablePath))
            {
                return new ResolvedJavaRuntime(match.ExecutablePath, targetMajor);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "依 Minecraft {Version} 尋找符合官方指定 major 的 Java 失敗", minecraftVersion);
        }

        return null;
    }

    public Task<ServerOperationResult> DeleteServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        return RunWithServerGateAsync(name, ct => DeleteServerCoreAsync(name, ct), cancellationToken);
    }

    private async Task<ServerOperationResult> DeleteServerCoreAsync(string name, CancellationToken cancellationToken)
    {
        var config = await GetServerAsync(name, cancellationToken).ConfigureAwait(false);
        if (config is null)
        {
            return ServerOperationResult.Fail($"找不到伺服器：{name}");
        }

        // 以伺服器清單檔記錄的實際路徑為準
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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "刪除伺服器「{Name}」失敗", name);
            return ServerOperationResult.Fail($"刪除伺服器失敗：{ex.Message}");
        }
    }

    public Task<ServerOperationResult> UpdateServerAsync(ServerConfig config, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(config);
        return RunWithServerGateAsync(config.Name.Value, ct => UpdateServerCoreAsync(config, ct), cancellationToken);
    }

    private async Task<ServerOperationResult> UpdateServerCoreAsync(ServerConfig config, CancellationToken cancellationToken)
    {
        var existing = await GetServerAsync(config.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is null)
        {
            return ServerOperationResult.Fail($"找不到要更新的伺服器：{config.Name.Value}");
        }

        // 先驗證再寫入清單，避免設定與啟動腳本不一致
        if (StartScriptWriter.DescribeRejectedJvmArgument(config.JvmArgs) is { } rejectedReason)
        {
            return ServerOperationResult.Fail(rejectedReason);
        }

        _registry.Set(config.Name.Value, config);

        if (SafeFileSystem.DirectoryExists(config.Path))
        {
            if (StartScriptWriter.UsesUserJvmArgsFile(config.LoaderType, config.Path))
            {
                StartScriptWriter.UpdateUserJvmArgs(config.Path, config);
            }
            else
            {
                StartScriptWriter.UpdateScriptJvmArgs(config.Path, config);
            }

            StartScriptWriter.UpdateMemory(config.Path, config);
        }

        string jvmText = config.JvmArgs is { Count: > 0 } ? string.Join(" ", config.JvmArgs) : "無";
        Logger.Information("伺服器「{Name}」設定更新成功 (記憶體: {Min}M-{Max}M, JVM參數: {Jvm})", config.Name.Value, config.MemoryMinMb, config.MemoryMaxMb, jvmText);
        return ServerOperationResult.Ok("更新伺服器設定成功");
    }

    public Task<ServerImportResult> ImportServerAsync(
        string sourceDirectory,
        string targetName,
        ImportTransferMode mode = ImportTransferMode.Copy,
        IProgress<ServerImportProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(targetName);
        return RunWithServerGateAsync(targetName, ct => _importWorkflow.ImportAsync(sourceDirectory, targetName, mode, progress, ct), cancellationToken);
    }

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
            catch (Exception exception) when (exception is not OperationCanceledException)
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

            if (inspection.MinecraftVersion is null)
            {
                Logger.Warning("目錄「{Name}」無法辨識 Minecraft 版本，已跳過", folderName);
                skipped++;
                continue;
            }

            var loaderKind = inspection.LoaderType is LoaderKind.Unknown ? LoaderKind.Vanilla : inspection.LoaderType;
            var config = ServerSetupHelpers.CreateConfigFromInspection(serverName, loaderKind, inspection, directory);

            newConfigs.Add((folderName, config));
            Logger.Information("偵測並預備註冊新伺服器「{Name}」：MC {MC} / {Loader}", folderName, config.MinecraftVersion.Value, loaderKind);
        }

        if (newConfigs.Count > 0)
        {
            // 掃描期間可能有同名伺服器被建立或匯入，不覆寫既有條目
            newlyAdded = _registry.Update(registry =>
            {
                int added = 0;
                foreach (var (folderName, config) in newConfigs)
                {
                    if (registry.TryAdd(folderName, ServerConfigPayload.FromDomain(config)))
                    {
                        added++;
                    }
                }

                return added;
            });
            alreadyManaged += newConfigs.Count - newlyAdded;
        }

        Logger.Information("伺服器偵測完成：已管理 {Managed}，新增 {Added}，跳過 {Skipped}", alreadyManaged, newlyAdded, skipped);
        return new ServerScanReport(alreadyManaged, newlyAdded, skipped);
    }

}
