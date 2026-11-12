using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器匯入流程：暫存解壓或複製、正規化結構、偵測核心、遷移屬性、寫入啟動腳本並寫入登錄檔</summary>
internal sealed class ServerImportWorkflow(
    string serversRoot,
    ServerRegistryStore registry,
    IServerInspector inspector,
    Func<string?, string, LoaderKind, CancellationToken, Task<string?>> resolveJavaExecutableAsync)
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerImportWorkflow));
    private readonly string _serversRoot = serversRoot;
    private readonly ServerRegistryStore _registry = registry;
    private readonly IServerInspector _inspector = inspector;
    private readonly Func<string?, string, LoaderKind, CancellationToken, Task<string?>> _resolveJavaExecutableAsync = resolveJavaExecutableAsync;

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
        string targetDir = Path.Combine(_serversRoot, targetName);
        bool targetExisted = SafeFileSystem.DirectoryExists(targetDir);
        if (targetExisted && !SafeFileSystem.IsDirectoryEmpty(targetDir))
        {
            Logger.Warning("匯入目標目錄已存在且非空: {TargetDir}", targetDir);
            return ServerImportResult.Failed(targetName, $"目標目錄已存在且非空：{targetDir}");
        }

        string stagingDir = Path.Combine(_serversRoot, $"{ServerDefaults.InternalPrefix}import-staging-{Guid.NewGuid():N}");
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
                    }, cancellationToken);
                }, cancellationToken).ConfigureAwait(false);
            }
            else
            {
                progress?.Report(new ServerImportProgressReport(20, "正在複製伺服器檔案..."));
                string stableSource = SafeFileSystem.ResolveStableDirectory(sourceDirectory);
                await Task.Run(() => SafeFileSystem.CopyDirectoryTreeSafe(stableSource, stagingDir, cancellationToken), cancellationToken).ConfigureAwait(false);
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
                AtomicFileWriter.WriteTextOrThrow(eulaFile, "eula=true\n");
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
                    Logger.Warning(ex, "伺服器匯入屬性遷移略過");
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
                    Logger.Warning(ex, "備份現有啟動腳本失敗");
                }
            }

            int memMax = inspection.MemoryMaxMb > 0 ? inspection.MemoryMaxMb : ServerDefaults.DefaultMemoryMaxMb;
            int memMin = inspection.MemoryMinMb is > 0 ? inspection.MemoryMinMb.Value : ServerDefaults.DefaultMemoryMinMb;
            string? importJavaPath = await _resolveJavaExecutableAsync(null, inspection.MinecraftVersion, loaderKind, cancellationToken).ConfigureAwait(false);
            StartScriptWriter.Write(stableStaging, launchTarget, memMax, memMin, importJavaPath, null, loaderKind);
            ServerSetupHelpers.CleanupRedundantStartupScripts(stableStaging);

            progress?.Report(new ServerImportProgressReport(90, "正在移入伺服器主資料夾..."));

            // 將 staging 移至 targetDir
            SafeFileSystem.ResolveStableDirectory(targetDir, create: true);
            SafeFileSystem.MoveChildren(stableStaging, targetDir);

            var config = ServerSetupHelpers.CreateConfigFromInspection(serverName, loaderKind, inspection, targetDir);

            _registry.Set(targetName, config);

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
            CleanupFailedTarget();
            return ServerImportResult.Failed(targetName, "已取消匯入伺服器");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "匯入伺服器「{Name}」失敗", targetName);
            CleanupFailedTarget();
            return ServerImportResult.Failed(targetName, $"匯入伺服器失敗：{ex.Message}");
        }
        finally
        {
            // DeleteWithin 對不存在的路徑與失敗皆自行處理並記錄
            SafeFileSystem.DeleteWithin(_serversRoot, stagingDir);
        }

        // 只清理本流程建立的目標目錄；原本就存在的（空）目錄僅清空本次搬入的內容
        void CleanupFailedTarget()
        {
            if (completedSuccessfully || !SafeFileSystem.DirectoryExists(targetDir))
            {
                return;
            }

            try
            {
                SafeFileSystem.DeleteWithin(_serversRoot, targetDir);
                if (targetExisted)
                {
                    SafeFileSystem.CreateDirectory(targetDir);
                }
            }
            catch (Exception cleanEx) when (cleanEx is not OperationCanceledException)
            {
                Logger.Warning(cleanEx, "匯入失敗後清理目標目錄失敗: {TargetDir}", targetDir);
            }
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
                if (SafeFileSystem.ListBoundedDirectory(wrapperPath, rejectReparse: false).Count == 0)
                {
                    break;
                }

                SafeFileSystem.MoveChildren(wrapperPath, stagingDir);

                SafeFileSystem.DeleteDirectory(wrapperPath, recursive: true);
            }
            else
            {
                break;
            }
        }
    }
}
