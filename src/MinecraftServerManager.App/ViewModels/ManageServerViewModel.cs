using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>管理伺服器頁面：組合清單、生命週期、備份與存放目錄子 ViewModel</summary>
public sealed partial class ManageServerViewModel : PageViewModel, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ManageServerViewModel));

    private readonly IUiService _ui;
    private readonly IServerManager _serverManager;
    private readonly IServerBackupService _backupService;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly IServerPlayerConfigStore _playerConfigStore;
    private readonly IServerInspector _serverInspector;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IExternalLauncher _launcher;

    public ManageServerViewModel(
        ServerListViewModel list,
        ServerLifecycleViewModel lifecycle,
        ServerBackupViewModel backup,
        ServersRootViewModel serversRoot,
        IServerManager serverManager,
        IServerBackupService backupService,
        IServerPropertiesStore propertiesStore,
        IServerPlayerConfigStore playerConfigStore,
        IServerInspector serverInspector,
        IServerRuntimeHost runtimeHost,
        ILocalFileSystem fileSystem,
        IExternalLauncher launcher,
        IUiService uiService)
        : base("管理現有伺服器")
    {
        ArgumentNullException.ThrowIfNull(list);
        ArgumentNullException.ThrowIfNull(lifecycle);
        ArgumentNullException.ThrowIfNull(backup);
        ArgumentNullException.ThrowIfNull(serversRoot);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(backupService);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentNullException.ThrowIfNull(playerConfigStore);
        ArgumentNullException.ThrowIfNull(serverInspector);
        ArgumentNullException.ThrowIfNull(runtimeHost);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(uiService);

        List = list;
        Lifecycle = lifecycle;
        Backup = backup;
        ServersRoot = serversRoot;
        _serverManager = serverManager;
        _backupService = backupService;
        _propertiesStore = propertiesStore;
        _playerConfigStore = playerConfigStore;
        _serverInspector = serverInspector;
        _runtimeHost = runtimeHost;
        _fileSystem = fileSystem;
        _launcher = launcher;
        _ui = uiService;

        List.RegisterDependentCommands(ConfigureServerCommand, ManagePlayersCommand, OpenServerFolderCommand, DeleteServerCommand, EditServerMemoryCommand, RecheckServerCommand);
    }

    /// <summary>伺服器清單與選取狀態</summary>
    public ServerListViewModel List { get; }

    /// <summary>伺服器啟動、停止與監控</summary>
    public ServerLifecycleViewModel Lifecycle { get; }

    /// <summary>伺服器備份與還原</summary>
    public ServerBackupViewModel Backup { get; }

    /// <summary>伺服器存放根目錄變更與遷移</summary>
    public ServersRootViewModel ServersRoot { get; }

    public void Dispose()
    {
        Lifecycle.Dispose();
        List.Dispose();
    }

    private bool HasSelectedServer() => List.HasSelectedServer;

    private bool CanManagePlayers() => List.CanManagePlayers;

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task ConfigureServerAsync() => List.RunForSelectedServerAsync(async selected =>
    {
        var vm = new ServerPropertiesViewModel(_propertiesStore, selected.Name, uiService: _ui);
        if (await _ui.ShowServerPropertiesAsync(vm) == true)
        {
            _ui.Notify($"伺服器「{selected.Name}」屬性設定已更新", NotificationType.Success);
        }
    }, "開啟屬性設定失敗", Logger);

    [RelayCommand(CanExecute = nameof(CanManagePlayers))]
    public Task ManagePlayersAsync() => List.RunForSelectedServerAsync(async selected =>
    {
        if (!_ui.EnsureServerStopped(List.IsSelectedServerActive, "伺服器正在執行中，請先停止伺服器後再管理玩家設定"))
        {
            return;
        }

        var vm = new PlayerManagementViewModel(
            serverName: selected.Name,
            serverPath: selected.Path,
            configStore: _playerConfigStore,
            ui: _ui);

        if (await _ui.ShowPlayerManagementAsync(vm) == true)
        {
            _ui.Notify($"伺服器「{selected.Name}」名單設定已更新", NotificationType.Success);
        }
    }, "開啟玩家名單失敗", Logger);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task OpenServerFolderAsync() => List.RunForSelectedServerAsync(async selected =>
    {
        if (!await _fileSystem.DirectoryExistsAsync(selected.Path))
        {
            _ui.Notify($"資料夾不存在：{selected.Path}", NotificationType.Warning);
            return;
        }

        _ui.OpenFolderOrWarn(_launcher, selected.Path);
    }, "開啟資料夾失敗", Logger);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task DeleteServerAsync() => List.RunForSelectedServerAsync(async currentServer =>
    {
        string name = currentServer.Name;
        if (!_ui.EnsureServerStopped(_runtimeHost, name, "刪除"))
        {
            return;
        }

        string? backupPath = currentServer.BackupPath;

        IReadOnlyList<ServerBackupInfo> backupsToDelete = [];
        if (!string.IsNullOrWhiteSpace(backupPath))
        {
            try
            {
                backupsToDelete = await _backupService.ListBackupsAsync(name, backupPath);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "取得伺服器「{Name}」關聯備份清單失敗", name);
            }
        }

        ServerDeleteDecision decision = await _ui.ShowServerDeleteConfirmationAsync(name, backupsToDelete.Count);
        if (decision == ServerDeleteDecision.Cancel)
        {
            return;
        }

        // 確認期間伺服器可能已被啟動
        if (!_ui.EnsureServerStopped(_runtimeHost, name, "刪除"))
        {
            return;
        }

        int backupFailures = decision == ServerDeleteDecision.DeleteServerAndBackups && backupsToDelete.Count > 0
            ? await DeleteBackupsAsync(name, backupPath!, backupsToDelete)
            : 0;

        var result = await _serverManager.DeleteServerAsync(name);
        if (backupFailures > 0)
        {
            _ui.Notify($"有 {backupFailures} 個備份檔案無法刪除，請至備份資料夾手動清除", NotificationType.Warning);
        }

        if (result.Success)
        {
            await _runtimeHost.ReleaseIdleRuntimeAsync(name);
            List.RemoveServer(currentServer);
            Logger.Information("伺服器「{Name}」已成功刪除", name);
            _ui.Notify($"已成功刪除伺服器「{name}」", NotificationType.Success);
        }
        else
        {
            Logger.Warning("刪除伺服器「{Name}」失敗：{Message}", name, result.Message);
            _ui.Notify($"刪除伺服器失敗：{result.Message}", NotificationType.Error);
        }
    }, "刪除伺服器失敗", Logger);

    /// <summary>逐一刪除備份並回傳失敗數量</summary>
    private async Task<int> DeleteBackupsAsync(string serverName, string backupPath, IReadOnlyList<ServerBackupInfo> backups)
    {
        int failures = 0;
        foreach (var backup in backups)
        {
            try
            {
                if (!await _backupService.DeleteBackupAsync(serverName, backup.FileName, backupPath))
                {
                    failures++;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                failures++;
                Logger.Warning(ex, "刪除伺服器「{Name}」的備份檔案「{File}」失敗", serverName, backup.FileName);
            }
        }

        Logger.Information("伺服器「{Name}」一併刪除備份：成功 {Succeeded} 個、失敗 {Failed} 個", serverName, backups.Count - failures, failures);
        return failures;
    }

    /// <summary>讀取伺服器設定；找不到時警告並回傳 null</summary>
    private Task<ServerConfig?> GetServerOrWarnAsync(string name) =>
        _ui.GetServerOrWarnAsync(_serverManager, name);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task EditServerMemoryAsync() => List.RunForSelectedServerAsync(async selected =>
    {
        if (await GetServerOrWarnAsync(selected.Name) is not { } config)
        {
            return;
        }

        var serverManager = _serverManager;
        var vm = new ServerMemoryViewModel(config, async (max, min) =>
        {
            var res = await serverManager.UpdateServerAsync(config.WithMemory(max, min));
            return res.Success;
        }, uiService: _ui, systemMemoryMb: Core.Utilities.MemoryHelpers.GetTotalSystemMemoryMb());

        if (await _ui.ShowServerMemoryAsync(vm) == true)
        {
            _ui.Notify($"已更新伺服器「{selected.Name}」記憶體設定", NotificationType.Success);
            await List.RefreshAndSelectServerAsync(selected.Name);
        }
    }, "編輯伺服器記憶體失敗", Logger);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task RecheckServerAsync() => List.RunForSelectedServerAsync(async selected =>
    {
        if (await GetServerOrWarnAsync(selected.Name) is not { } config)
        {
            return;
        }

        var inspection = await _serverInspector.InspectAsync(selected.Path);
        if (!inspection.IsCandidate)
        {
            _ui.Notify("重新偵測失敗：目錄不包含有效的 Minecraft 伺服器檔案", NotificationType.Error);
            return;
        }

        var lk = inspection.LoaderType is LoaderKind.Unknown ? config.LoaderType : inspection.LoaderType;
        var mv = inspection.MinecraftVersion ?? config.MinecraftVersion;
        var updated = config.WithLoader(mv, lk, inspection.LoaderVersion ?? ServerDefaults.UnknownLoaderVersion);

        await List.UpdateSelectedServerConfigAsync(
            _ => updated,
            successMessage: string.Empty,
            failureTitle: "重新偵測完成，但更新設定失敗",
            logger: Logger);

        _ui.ShowNotification($"已重新偵測伺服器：{config.Name.Value}\nMinecraft 版本：{mv.Value}\n載入器類型：{lk}\n載入器版本：{updated.LoaderVersion}", "重新偵測完成", NotificationType.Success);
    }, "伺服器重新偵測失敗", Logger);
}
