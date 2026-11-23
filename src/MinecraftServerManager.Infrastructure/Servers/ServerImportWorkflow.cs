using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器匯入流程</summary>
internal sealed class ServerImportWorkflow
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerImportWorkflow));

    private readonly string _serversRoot;
    private readonly ServerRegistryStore _registry;
    private readonly IServerInspector _inspector;
    private readonly Func<string?, string, CancellationToken, Task<ResolvedJavaRuntime?>> _resolveJavaExecutableAsync;

    public ServerImportWorkflow(
        string serversRoot,
        ServerRegistryStore registry,
        IServerInspector inspector,
        Func<string?, string, CancellationToken, Task<ResolvedJavaRuntime?>> resolveJavaExecutableAsync)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        ArgumentNullException.ThrowIfNull(registry);
        ArgumentNullException.ThrowIfNull(inspector);
        ArgumentNullException.ThrowIfNull(resolveJavaExecutableAsync);
        _serversRoot = serversRoot;
        _registry = registry;
        _inspector = inspector;
        _resolveJavaExecutableAsync = resolveJavaExecutableAsync;
    }

    public async Task<ServerImportResult> ImportAsync(
        string sourceDirectory,
        string targetName,
        ImportTransferMode mode = ImportTransferMode.Copy,
        IProgress<ServerImportProgressReport>? progress = null,
        CancellationToken cancellationToken = default)
    {
        Logger.Information("開始匯入伺服器「{Name}」 (來源: {Source}, 模式: {Mode})", targetName, sourceDirectory, mode);

        if (!ServerName.TryParse(targetName, out var serverName))
        {
            Logger.Warning("匯入伺服器名稱無效: {Name}", targetName);
            return ServerImportResult.Failed(targetName, "無效的伺服器名稱");
        }

        var existing = _registry.Find(targetName);
        if (existing is not null)
        {
            Logger.Warning("匯入伺服器已存在同名者: {Name}", targetName);
            return ServerImportResult.Failed(targetName, $"已存在同名的伺服器：{targetName}");
        }

        bool isZip = SafeFileSystem.FileExists(sourceDirectory) && sourceDirectory.EndsWith(".zip", StringComparison.OrdinalIgnoreCase);
        if (!isZip && DescribeUnsafeSourceDirectory(sourceDirectory, mode) is { } unsafeReason)
        {
            Logger.Warning("匯入來源目錄不安全（{Reason}）: {Source}", unsafeReason, sourceDirectory);
            return ServerImportResult.Failed(targetName, unsafeReason);
        }

        string targetDir = Path.Combine(_serversRoot, targetName);
        if (ServerSetupHelpers.ValidateEmptyTargetDirectory(targetDir, out bool targetExisted) is { } targetError)
        {
            Logger.Warning("匯入目標目錄已存在且非空: {TargetDir}", targetDir);
            return ServerImportResult.Failed(targetName, targetError);
        }

        progress?.Report(new ServerImportProgressReport(5, "正在準備暫存環境..."));
        using EphemeralStagingScope staging = new(_serversRoot, targetDir, targetExisted, "import-staging");
        string stableStaging = staging.StableStaging;

        try
        {
            if (isZip)
            {
                progress?.Report(new ServerImportProgressReport(10, "正在解壓縮伺服器封存檔..."));
                await Task.Run(() =>
                {
                    SafeZipArchive.Extract(sourceDirectory, stableStaging, (extracted, total) =>
                    {
                        int pct = ProgressMapping.Map(extracted, total, 10, 55, unknown: 35);
                        progress?.Report(new ServerImportProgressReport(pct, $"正在解壓縮檔案 ({pct}%)..."));
                    }, cancellationToken);
                }, cancellationToken).ConfigureAwait(false);
            }
            else
            {
                progress?.Report(new ServerImportProgressReport(15, "正在檢查磁碟可用空間..."));
                string stableSource = SafeFileSystem.ResolveStableDirectory(sourceDirectory);
                long requiredBytes = 0;
                foreach (var entry in SafeFileSystem.EnumerateBoundedTree(stableSource, rejectReparse: true))
                {
                    if (!entry.IsDirectory)
                    {
                        requiredBytes += entry.Length;
                    }
                }

                if (ServerSetupHelpers.CheckFreeSpace(stableStaging, requiredBytes) is { } insufficientSpace)
                {
                    return ServerImportResult.Failed(targetName, insufficientSpace);
                }

                progress?.Report(new ServerImportProgressReport(20, "正在複製伺服器檔案..."));
                await Task.Run(() => SafeFileSystem.CopyDirectoryTreeSafe(stableSource, stableStaging, cancellationToken), cancellationToken).ConfigureAwait(false);
            }

            progress?.Report(new ServerImportProgressReport(60, "正在正規化伺服器檔案結構..."));
            FlattenSingleWrapper(stableStaging);

            progress?.Report(new ServerImportProgressReport(70, "正在分析 Minecraft 核心與載入器..."));
            var inspection = await _inspector.InspectAsync(stableStaging, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (!inspection.IsCandidate)
            {
                Logger.Warning("來源目錄不包含有效的 Minecraft 伺服器檔案: {Source}", sourceDirectory);
                return ServerImportResult.Failed(targetName, "來源目錄不包含有效的 Minecraft 伺服器檔案 (未找到伺服器核心 jar 或關鍵執行檔案)");
            }

            if (inspection.MinecraftVersion is null)
            {
                Logger.Warning("無法辨識匯入來源的 Minecraft 版本: {Source}", sourceDirectory);
                return ServerImportResult.Failed(targetName, ServerSetupHelpers.UnknownVersionMessage);
            }

            progress?.Report(new ServerImportProgressReport(80, "正在設定伺服器環境與屬性..."));
            staging.EnsureEula();

            // 自動遷移舊版 server.properties 屬性
            string propsPath = Path.Combine(stableStaging, ServerDefaults.ServerPropertiesFileName);
            if (SafeFileSystem.FileExists(propsPath))
            {
                try
                {
                    string propsContent = await SafeFileSystem.ReadAllTextAsync(propsPath, Encoding.UTF8, cancellationToken: cancellationToken).ConfigureAwait(false);
                    var rawProps = PropertiesDocumentCodec.Parse(propsContent);
                    var migrationPlan = ServerPropertiesMigrationService.PlanMigration(rawProps, inspection.MinecraftVersion.Value.Value);
                    if (migrationPlan.NeedsMigration)
                    {
                        ServerPropertiesMigrationService.ApplyMigrationToDirectory(stableStaging, migrationPlan, createBackup: true);
                        Logger.Information("伺服器「{Name}」匯入時已自動遷移 server.properties 設定", targetName);
                    }
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Warning(ex, "伺服器匯入屬性遷移略過");
                }
            }

            progress?.Report(new ServerImportProgressReport(85, "正在維護受管啟動腳本..."));
            var loaderKind = inspection.LoaderType is LoaderKind.Unknown ? LoaderKind.Vanilla : inspection.LoaderType;
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
                    Logger.Warning(ex, "備份現有啟動腳本失敗");
                }
            }

            int memMax = inspection.MemoryMaxMb > 0 ? inspection.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb;
            ResolvedJavaRuntime? importJava = await _resolveJavaExecutableAsync(null, inspection.MinecraftVersion.Value.Value, cancellationToken).ConfigureAwait(false);
            ServerSetupHelpers.FinalizeLaunchScripts(stableStaging, launchTarget, memMax, inspection.MemoryMinMb, importJava?.ExecutablePath, null, loaderKind, importJava?.MajorVersion);

            progress?.Report(new ServerImportProgressReport(90, "正在移入伺服器主資料夾..."));

            // 整目錄原子 MoveWithin 至 targetDir
            if (!staging.TryCommitToTarget())
            {
                return ServerImportResult.Failed(targetName, "原子移動暫存目錄至正式伺服器目錄失敗");
            }

            var config = ServerSetupHelpers.CreateConfigFromInspection(serverName, loaderKind, inspection, targetDir);

            _registry.Set(targetName, config);
            staging.Complete();

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
                    Logger.Warning(moveCleanEx, "遷移匯入完成後移除原始來源失敗: {SourceDirectory}", sourceDirectory);
                }
            }

            progress?.Report(new ServerImportProgressReport(100, "伺服器匯入完成！"));
            Logger.Information("伺服器「{Name}」匯入成功！目標路徑: {Path}, MC: {MC}, Loader: {Loader}", targetName, targetDir, config.MinecraftVersion.Value, loaderKind);
            return ServerImportResult.Success(targetName, config);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("使用者已取消匯入伺服器「{Name}」", targetName);
            return ServerImportResult.Failed(targetName, "已取消匯入伺服器");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "匯入伺服器「{Name}」失敗", targetName);
            return ServerImportResult.Failed(targetName, $"匯入伺服器失敗：{ex.Message}");
        }
    }

    /// <summary>來源為磁碟根目錄、伺服器根目錄或其上層時回傳拒絕原因；遷移模式會遞迴刪除來源，另禁止與已註冊伺服器重疊</summary>
    private string? DescribeUnsafeSourceDirectory(string sourceDirectory, ImportTransferMode mode)
    {
        string source = Path.TrimEndingDirectorySeparator(Path.GetFullPath(sourceDirectory));
        if (Path.GetPathRoot(source) is { Length: > 0 } volumeRoot &&
            string.Equals(Path.TrimEndingDirectorySeparator(volumeRoot), source, StringComparison.OrdinalIgnoreCase))
        {
            return "來源不可為磁碟根目錄";
        }

        string serversRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(_serversRoot));
        if (string.Equals(source, serversRoot, StringComparison.OrdinalIgnoreCase) ||
            serversRoot.StartsWith(source + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        {
            return "來源不可為伺服器存放根目錄或其上層資料夾";
        }

        if (mode == ImportTransferMode.Move)
        {
            foreach (var server in _registry.GetAll())
            {
                if (string.IsNullOrWhiteSpace(server.Path))
                {
                    continue;
                }

                string serverPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(server.Path));
                if (SafeFileSystem.IsPathWithin(serverPath, source, strict: false) || SafeFileSystem.IsPathWithin(source, serverPath, strict: false))
                {
                    return $"遷移模式的來源不可與已註冊的伺服器「{server.Name.Value}」目錄重疊";
                }
            }
        }

        return null;
    }

    private static void FlattenSingleWrapper(string stagingDir)
    {
        for (int i = 0; i < 3; i++)
        {
            var entries = SafeFileSystem.ListBoundedDirectory(stagingDir, rejectReparse: false);
            if (entries.Count == 1 && entries[0].IsDirectory)
            {
                string wrapperPath = entries[0].FullPath;
                if (SafeFileSystem.IsDirectoryEmpty(wrapperPath))
                {
                    break;
                }

                // 先改為暫存名稱，避免包裝資料夾內含同名子項目（如 server/server）時搬移衝突
                string renamedWrapper = Path.Combine(stagingDir, $"{ServerDefaults.InternalPrefix}flatten-{Guid.NewGuid():N}");
                SafeFileSystem.MovePath(wrapperPath, renamedWrapper, overwrite: false);
                SafeFileSystem.MoveChildren(renamedWrapper, stagingDir);

                SafeFileSystem.DeleteDirectory(renamedWrapper, recursive: true);
            }
            else
            {
                break;
            }
        }
    }
}
