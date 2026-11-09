using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 管理伺服器頁面 ViewModel：組合清單、生命週期、備份與存放目錄子 ViewModel，並負責各設定對話框的開啟
/// </summary>
public sealed partial class ManageServerViewModel : PageViewModel, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ManageServerViewModel));

    private readonly IUiService _ui;
    private readonly MainViewModelDependencies _services;

    /// <summary>
    /// 伺服器清單與選取狀態
    /// </summary>
    public ServerListViewModel List { get; }

    /// <summary>
    /// 伺服器啟動、停止與監控
    /// </summary>
    public ServerLifecycleViewModel Lifecycle { get; }

    /// <summary>
    /// 伺服器備份與還原
    /// </summary>
    public ServerBackupViewModel Backup { get; }

    /// <summary>
    /// 伺服器存放根目錄變更與遷移
    /// </summary>
    public ServersRootViewModel ServersRoot { get; }

    public ManageServerViewModel(
        MainViewModelDependencies services,
        IUiService uiService,
        Action<string> navigateCallback)
        : base("管理現有伺服器")
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(navigateCallback);
        _ui = uiService;
        _services = services;

        List = new ServerListViewModel(
            services.SettingsManager,
            services.ServerManager,
            services.BackupService,
            services.ServerRuntime,
            services.IntegrityService,
            services.DirectorySizeService,
            services.FileSystem,
            _ui,
            navigateCallback);

        Lifecycle = new ServerLifecycleViewModel(
            services.ServerManager,
            services.ServerRuntime,
            services.ServerInspector,
            services.LaunchPlanner,
            services.LogReader,
            services.PropertiesStore,
            services.FileSystem,
            List,
            _ui,
            services.JavaDetector,
            services.JavaRequirementService);

        Backup = new ServerBackupViewModel(
            services.ServerManager,
            services.BackupService,
            services.ServerRuntime,
            services.FileSystem,
            List,
            _ui,
            services.Launcher);

        ServersRoot = new ServersRootViewModel(
            services.SettingsManager,
            services.ServersRootService,
            services.ServerRuntime,
            services.FileSystem,
            List,
            _ui);

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

        var vm = new ServerPropertiesViewModel(_services.PropertiesStore, selected.Name, uiService: _ui);
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
            _ui.Notify("伺服器正在運行中，請先停止伺服器後再管理玩家設定", NotificationType.Warning);
            return;
        }

        var vm = new PlayerManagementViewModel(
            serverName: selected.Name,
            serverPath: selected.Path,
            configStore: _services.PlayerConfigStore,
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

        if (!_services.FileSystem.DirectoryExists(selected.Path))
        {
            _ui.Notify($"資料夾不存在：{selected.Path}", NotificationType.Warning);
            return Task.CompletedTask;
        }

        if (!_services.Launcher.OpenFolder(selected.Path))
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
        string? backupPath = currentServer.BackupPath;

        IReadOnlyList<ServerBackupInfo> backupsToDelete = [];
        if (!string.IsNullOrWhiteSpace(backupPath))
        {
            try
            {
                backupsToDelete = await _services.BackupService.ListBackupsAsync(name, backupPath);
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

            var result = await _services.ServerManager.DeleteServerAsync(name);
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
            Logger.Error(ex, "刪除伺服器失敗: {Message}", ex.Message);
            _ui.Notify($"刪除伺服器失敗：{ex.Message}", NotificationType.Error);
        }
    }

    private async Task DeleteBackupsAsync(string serverName, string backupPath, IReadOnlyList<ServerBackupInfo> backups)
    {
        try
        {
            foreach (var backup in backups)
            {
                await _services.BackupService.DeleteBackupAsync(serverName, backup.FileName, backupPath);
            }

            Logger.Information("伺服器「{Name}」的 {Count} 個備份檔案已一併刪除", serverName, backups.Count);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("刪除伺服器「{Name}」的備份檔案時發生錯誤: {Error}", serverName, ex.Message);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task EditServerMemory()
    {
        if (List.SelectedServer is not { } selected)
        {
            return;
        }

        var serverManager = _services.ServerManager;
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

        var config = await _services.ServerManager.GetServerAsync(selected.Name);
        if (config is null)
        {
            return;
        }

        try
        {
            var inspection = await _services.ServerInspector.InspectAsync(selected.Path);
            if (!inspection.IsCandidate)
            {
                _ui.Notify("重新偵測失敗：目錄不包含有效的 Minecraft 伺服器檔案", NotificationType.Error);
                return;
            }

            var lk = LoaderKinds.ParseOrDefault(inspection.LoaderType, config.LoaderType);
            var mv = MinecraftVersion.TryParse(inspection.MinecraftVersion, out var parsedMv) ? parsedMv : config.MinecraftVersion;

            var updated = config.WithLoader(mv, lk, inspection.LoaderVersion);

            await _services.ServerManager.UpdateServerAsync(updated);
            await List.RefreshAndSelectServerAsync(config.Name.Value);

            _ui.ShowNotification($"已重新偵測伺服器：{config.Name.Value}\nMinecraft 版本：{mv.Value}\n載入器類型：{lk}\n載入器版本：{updated.LoaderVersion}", "重新偵測完成", NotificationType.Success);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "伺服器重新偵測失敗：{Message}", ex.Message);
            _ui.Notify($"重新偵測失敗：{ex.Message}", NotificationType.Error);
        }
    }
}
