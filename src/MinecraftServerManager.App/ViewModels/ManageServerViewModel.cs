using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>管理伺服器頁面 ViewModel：組合清單、生命週期、備份與存放目錄子 ViewModel，並負責各設定對話框的開啟</summary>
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

    /// <summary>伺服器清單與選取狀態</summary>
    public ServerListViewModel List { get; }

    /// <summary>伺服器啟動、停止與監控</summary>
    public ServerLifecycleViewModel Lifecycle { get; }

    /// <summary>伺服器備份與還原</summary>
    public ServerBackupViewModel Backup { get; }

    /// <summary>伺服器存放根目錄變更與遷移</summary>
    public ServersRootViewModel ServersRoot { get; }

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

        List.SelectionStateChanged += OnSelectionStateChanged;
    }

    public void Dispose()
    {
        List.SelectionStateChanged -= OnSelectionStateChanged;
        Lifecycle.Dispose();
        Backup.Dispose();
        List.Dispose();
    }

    private bool HasSelectedServer() => List.HasSelectedServer;

    private void OnSelectionStateChanged()
    {
        ConfigureServerCommand.NotifyCanExecuteChanged();
        ManagePlayersCommand.NotifyCanExecuteChanged();
        OpenServerFolderCommand.NotifyCanExecuteChanged();
        DeleteServerCommand.NotifyCanExecuteChanged();
        EditServerMemoryCommand.NotifyCanExecuteChanged();
        RecheckServerCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task ConfigureServerAsync()
    {
        if (List.SelectedServer is not { } selected)
        {
            return;
        }

        var vm = new ServerPropertiesViewModel(_propertiesStore, selected.Name, uiService: _ui);
        if (await _ui.ShowServerPropertiesAsync(vm) == true)
        {
            _ui.Notify($"伺服器「{selected.Name}」屬性設定已更新", NotificationType.Success);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task ManagePlayersAsync()
    {
        if (List.SelectedServer is not { } selected)
        {
            return;
        }

        if (List.IsSelectedServerActive)
        {
            _ui.Notify("伺服器正在執行中，請先停止伺服器後再管理玩家設定", NotificationType.Warning);
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
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task OpenServerFolder()
    {
        if (List.SelectedServer is not { } selected)
        {
            return Task.CompletedTask;
        }

        if (!_fileSystem.DirectoryExists(selected.Path))
        {
            _ui.Notify($"資料夾不存在：{selected.Path}", NotificationType.Warning);
            return Task.CompletedTask;
        }

        if (!_launcher.OpenFolder(selected.Path))
        {
            _ui.Notify($"無法開啟資料夾：{selected.Path}", NotificationType.Warning);
        }

        return Task.CompletedTask;
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task DeleteServer()
    {
        if (List.SelectedServer is not { } currentServer)
        {
            return;
        }

        string name = currentServer.Name;
        if (_runtimeHost.IsRunning(name))
        {
            _ui.Notify("伺服器正在執行中，請先停止伺服器後再刪除", NotificationType.Warning);
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

        try
        {
            if (decision == ServerDeleteDecision.DeleteServerAndBackups && backupsToDelete.Count > 0)
            {
                await DeleteBackupsAsync(name, backupPath!, backupsToDelete);
            }

            var result = await _serverManager.DeleteServerAsync(name);
            if (result.Success)
            {
                List.RemoveServer(currentServer);
                Logger.Information("伺服器「{Name}」已成功刪除", name);
                _ui.Notify($"已成功刪除伺服器「{name}」", NotificationType.Success);
            }
            else
            {
                Logger.Warning("刪除伺服器「{Name}」失敗: {Message}", name, result.Message);
                _ui.Notify($"刪除伺服器失敗：{result.Message}", NotificationType.Error);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "刪除伺服器失敗");
            _ui.Notify($"刪除伺服器失敗：{ex.Message}", NotificationType.Error);
        }
    }

    private async Task DeleteBackupsAsync(string serverName, string backupPath, IReadOnlyList<ServerBackupInfo> backups)
    {
        try
        {
            foreach (var backup in backups)
            {
                await _backupService.DeleteBackupAsync(serverName, backup.FileName, backupPath);
            }

            Logger.Information("伺服器「{Name}」的 {Count} 個備份檔案已一併刪除", serverName, backups.Count);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "刪除伺服器「{Name}」的備份檔案時發生錯誤", serverName);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task EditServerMemory()
    {
        if (List.SelectedServer is not { } selected)
        {
            return;
        }

        var serverManager = _serverManager;
        var config = await serverManager.GetServerAsync(selected.Name);
        if (config is null)
        {
            return;
        }

        var vm = new ServerMemoryViewModel(config, async (max, min) =>
        {
            var updated = config.WithMemory(max, min);

            var res = await serverManager.UpdateServerAsync(updated);
            return res.Success;
        }, uiService: _ui, systemMemoryMb: Core.Utilities.MemoryUtils.GetTotalSystemMemoryMb());

        if (await _ui.ShowServerMemoryAsync(vm) == true)
        {
            _ui.Notify($"已更新伺服器「{selected.Name}」記憶體設定", NotificationType.Success);
            await List.RefreshAndSelectServerAsync(selected.Name);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task RecheckServer()
    {
        if (List.SelectedServer is not { } selected)
        {
            return;
        }

        var config = await _serverManager.GetServerAsync(selected.Name);
        if (config is null)
        {
            return;
        }

        try
        {
            var inspection = await _serverInspector.InspectAsync(selected.Path);
            if (!inspection.IsCandidate)
            {
                _ui.Notify("重新偵測失敗：目錄不包含有效的 Minecraft 伺服器檔案", NotificationType.Error);
                return;
            }

            var lk = LoaderKinds.ParseOrDefault(inspection.LoaderType, config.LoaderType);
            var mv = MinecraftVersion.TryParse(inspection.MinecraftVersion, out var parsedMv) ? parsedMv : config.MinecraftVersion;

            var updated = config.WithLoader(mv, lk, inspection.LoaderVersion);

            await _serverManager.UpdateServerAsync(updated);
            await List.RefreshAndSelectServerAsync(config.Name.Value);

            _ui.ShowNotification($"已重新偵測伺服器：{config.Name.Value}\nMinecraft 版本：{mv.Value}\n載入器類型：{lk}\n載入器版本：{updated.LoaderVersion}", "重新偵測完成", NotificationType.Success);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "伺服器重新偵測失敗");
            _ui.Notify($"重新偵測失敗：{ex.Message}", NotificationType.Error);
        }
    }
}
