using System.Text;
using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器集中管理服務實作
/// </summary>
public sealed class ServerManager : IServerManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerManager");
    private readonly string _serversRoot;
    private readonly string _registryFilePath;
    private readonly IServerInspector _inspector;
    private readonly ILoaderInstallerService? _loaderInstaller;
    private readonly object _lock = new();

    public ServerManager(
        string serversRoot,
        IServerInspector? inspector = null,
        ILoaderInstallerService? loaderInstaller = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        _serversRoot = SafeFileSystem.ResolveStableDirectory(serversRoot, create: true);
        _registryFilePath = Path.Combine(_serversRoot, "servers.json");
        _inspector = inspector ?? new ServerInspector();
        _loaderInstaller = loaderInstaller;

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

    public async Task<ServerConfig?> GetServerAsync(string name, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        var servers = await GetAllServersAsync(cancellationToken).ConfigureAwait(false);
        return servers.FirstOrDefault(s => s.Name.Value.Equals(name, StringComparison.OrdinalIgnoreCase));
    }

    public async Task<ServerCreationResult> CreateServerAsync(
        ServerCreationPlan plan,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(plan);
        cancellationToken.ThrowIfCancellationRequested();

        var existing = await GetServerAsync(plan.Name.Value, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            return ServerCreationResult.Failed($"已存在同名的伺服器：{plan.Name.Value}");
        }

        string serverDir = Path.Combine(_serversRoot, plan.Name.Value);
        bool createdDir = false;

        Logger.Information("開始建立伺服器「{Name}」 (MC: {McVer}, 載入器: {Loader} {LoaderVer}, 記憶體: {MemMax}MB)", plan.Name.Value, plan.MinecraftVersion.Value, plan.LoaderType, plan.LoaderVersion, plan.MemoryMaxMb);

        try
        {
            // 建立伺服器目錄
            SafeFileSystem.ResolveStableDirectory(serverDir, create: true);
            createdDir = true;

            // 寫入 eula.txt
            string eulaPath = Path.Combine(serverDir, "eula.txt");
            AtomicFileWriter.WriteText(eulaPath, "eula=true\n");

            // 寫入初始 server.properties
            string propertiesPath = Path.Combine(serverDir, "server.properties");
            var initialProps = new Dictionary<string, string>(ServerPropertiesMetadata.DefaultProperties)
            {
                ["motd"] = $"A Minecraft Server ({plan.Name.Value})",
                ["server-port"] = "25565",
            };
            string propsText = PropertiesDocumentCodec.Serialize(initialProps);
            AtomicFileWriter.WriteText(propertiesPath, propsText);

            // 若有提供 Loader 安裝器則執行核心下載與安裝
            if (_loaderInstaller is not null)
            {
                string javaPath = !string.IsNullOrWhiteSpace(plan.UserJavaPath) ? plan.UserJavaPath : "java";
                Logger.Information("開始下載與安裝伺服器核心 (載入器: {Loader})", plan.LoaderType);
                await _loaderInstaller.InstallLoaderAsync(
                    loader: plan.LoaderType,
                    minecraftVersion: plan.MinecraftVersion.Value,
                    loaderVersion: plan.LoaderVersion,
                    serverDirectory: serverDir,
                    javaExecutablePath: javaPath,
                    cancellationToken: cancellationToken).ConfigureAwait(false);
            }

            // 產出設定與登記
            var config = plan.BuildConfig(serverDir);
            lock (_lock)
            {
                var registry = LoadRegistry();
                registry[plan.Name.Value] = ServerConfigPayload.FromDomain(config);
                SaveRegistry(registry);
            }

            Logger.Information("伺服器「{Name}」建立成功！路徑: {Path}", plan.Name.Value, serverDir);
            return ServerCreationResult.Success(config);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器「{Name}」失敗: {Message}", plan.Name.Value, ex.Message);
            if (createdDir)
            {
                try
                {
                    SafeFileSystem.DeleteWithin(_serversRoot, serverDir);
                }
                catch
                {
                }
            }
            return ServerCreationResult.Failed($"建立伺服器時發生例外：{ex.Message}");
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

        string serverDir = Path.Combine(_serversRoot, name);

        Logger.Information("開始刪除伺服器「{Name}」...", name);

        try
        {
            // 兩階段安全刪除
            if (Directory.Exists(serverDir))
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

        string jvmText = config.JvmArgs is { Count: > 0 } ? string.Join(" ", config.JvmArgs) : "無";
        Logger.Information("伺服器「{Name}」設定更新成功 (記憶體: {Min}M-{Max}M, JVM參數: {Jvm})", config.Name.Value, config.MemoryMinMb, config.MemoryMaxMb, jvmText);
        return ServerOperationResult.Ok("更新伺服器設定成功");
    }

    public async Task<ServerImportResult> ImportServerAsync(
        string sourceDirectory,
        string targetName,
        ImportTransferMode mode = ImportTransferMode.Copy,
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

        bool isZip = File.Exists(sourceDirectory) && sourceDirectory.EndsWith(".zip", StringComparison.OrdinalIgnoreCase);
        string targetDir = Path.Combine(_serversRoot, targetName);
        string stagingDir = Path.Combine(_serversRoot, $".import-staging-{Guid.NewGuid():N}");
        bool completedSuccessfully = false;

        try
        {
            Directory.CreateDirectory(stagingDir);

            if (isZip)
            {
                SafeZipArchive.Extract(sourceDirectory, stagingDir);
            }
            else if (mode == ImportTransferMode.Copy)
            {
                string stableSource = SafeFileSystem.ResolveStableDirectory(sourceDirectory);
                CopyDirectoryTreeSafe(stableSource, stagingDir);
            }
            else
            {
                string stableSource = SafeFileSystem.ResolveStableDirectory(sourceDirectory);
                SafeFileSystem.MoveWithin(_serversRoot, stableSource, stagingDir);
            }

            string stableStaging = SafeFileSystem.ResolveStableDirectory(stagingDir);
            var inspection = await _inspector.InspectAsync(stableStaging, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (!inspection.IsCandidate)
            {
                Logger.Warning("來源目錄不包含有效的 Minecraft 伺服器檔案: {Source}", sourceDirectory);
                return ServerImportResult.Failed(targetName, "來源目錄不包含有效的 Minecraft 伺服器檔案");
            }

            // 確保 eula.txt 存在
            string eulaFile = Path.Combine(stableStaging, "eula.txt");
            if (!File.Exists(eulaFile))
            {
                AtomicFileWriter.WriteText(eulaFile, "eula=true\n");
            }

            // 自動遷移舊版 server.properties 屬性
            string propsPath = Path.Combine(stableStaging, "server.properties");
            if (File.Exists(propsPath))
            {
                try
                {
                    string propsContent = await File.ReadAllTextAsync(propsPath, Encoding.UTF8, cancellationToken).ConfigureAwait(false);
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

            // 將 staging 移至 targetDir
            SafeFileSystem.ResolveStableDirectory(targetDir, create: true);
            var stagingEntries = SafeFileSystem.ListBoundedDirectory(stableStaging, rejectReparse: false);
            foreach (var entry in stagingEntries)
            {
                string dest = Path.Combine(targetDir, Path.GetFileName(entry.FullPath));
                if (entry.IsDirectory)
                {
                    Directory.Move(entry.FullPath, dest);
                }
                else
                {
                    File.Move(entry.FullPath, dest);
                }
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
                path: targetDir);

            lock (_lock)
            {
                var registry = LoadRegistry();
                registry[targetName] = ServerConfigPayload.FromDomain(config);
                SaveRegistry(registry);
            }

            completedSuccessfully = true;
            Logger.Information("伺服器「{Name}」匯入成功！目標路徑: {Path}, MC: {MC}, Loader: {Loader}", targetName, targetDir, mcVersion.Value, loaderKind);
            return ServerImportResult.Success(targetName, config);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "匯入伺服器「{Name}」失敗: {Message}", targetName, ex.Message);
            if (!completedSuccessfully && Directory.Exists(targetDir))
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
            if (Directory.Exists(stagingDir))
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

    private Dictionary<string, ServerConfigPayload> LoadRegistry()
    {
        if (!File.Exists(_registryFilePath))
        {
            return new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
        }

        try
        {
            string json = File.ReadAllText(_registryFilePath, Encoding.UTF8);
            return JsonCodec.Deserialize<Dictionary<string, ServerConfigPayload>>(json)
                   ?? new Dictionary<string, ServerConfigPayload>(StringComparer.OrdinalIgnoreCase);
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
    }

    private static void CopyDirectoryTreeSafe(string source, string destination)
    {
        var entries = SafeFileSystem.WalkBoundedTree(source, rejectReparse: true);
        foreach (var entry in entries)
        {
            string rel = Path.GetRelativePath(source, entry.FullPath);
            string target = Path.Combine(destination, rel);

            if (entry.IsDirectory)
            {
                Directory.CreateDirectory(target);
            }
            else
            {
                string? dir = Path.GetDirectoryName(target);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                {
                    Directory.CreateDirectory(dir);
                }
                File.Copy(entry.FullPath, target, overwrite: true);
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
}
