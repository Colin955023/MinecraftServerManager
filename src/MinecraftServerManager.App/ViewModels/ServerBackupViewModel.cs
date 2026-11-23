using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器管理頁：建立備份、還原備份與外部備份資料夾設定</summary>
public sealed partial class ServerBackupViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerBackupViewModel));

    private readonly IUiService _ui;
    private readonly IServerManager _serverManager;
    private readonly IServerBackupService _backupService;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IExternalLauncher _launcher;
    private readonly ServerListViewModel _list;

    public ServerBackupViewModel(
        IServerManager serverManager,
        IServerBackupService backupService,
        IServerRuntimeHost runtimeHost,
        ILocalFileSystem fileSystem,
        ServerListViewModel list,
        IUiService uiService,
        IExternalLauncher launcher)
    {
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(backupService);
        ArgumentNullException.ThrowIfNull(runtimeHost);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(list);

        _ui = uiService;
        _serverManager = serverManager;
        _backupService = backupService;
        _runtimeHost = runtimeHost;
        _fileSystem = fileSystem;
        _launcher = launcher;
        _list = list;
        _list.RegisterDependentCommands(BackupServerCommand, RestoreBackupCommand, OpenBackupFolderCommand, EditBackupPathCommand);
    }

    private bool HasSelectedServer() => _list.HasSelectedServer;

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task BackupServerAsync() => _list.RunForSelectedServerAsync(async selected =>
    {
        string serverName = selected.Name;

        if (!_ui.EnsureServerStopped(_runtimeHost, serverName, "備份", "無法備份"))
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(selected.BackupPath))
        {
            _ui.ShowNotification("伺服器尚未設定外部備份資料夾，請先設定儲存位置", "請設定備份路徑", NotificationType.Warning);
            await EditBackupPathAsync();
            selected = _list.SelectedServer ?? selected;
            if (string.IsNullOrWhiteSpace(selected.BackupPath))
            {
                return;
            }
        }

        string destinationDir = selected.BackupPath;
        if (await _backupService.ValidateBackupDestinationAsync(destinationDir) is { } boundaryViolation)
        {
            _ui.ShowNotification(boundaryViolation, "備份路徑無效，請重新設定", NotificationType.Warning);
            await EditBackupPathAsync();
            selected = _list.SelectedServer ?? selected;
            if (string.IsNullOrWhiteSpace(selected.BackupPath) || await _backupService.ValidateBackupDestinationAsync(selected.BackupPath) is not null)
            {
                return;
            }

            destinationDir = selected.BackupPath;
        }

        string destinationPath;
        try
        {
            destinationPath = await _backupService.PrepareBackupFilePathAsync(serverName, destinationDir);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "建立備份目錄失敗");
            _ui.Notify($"建立備份目錄失敗：{ex.Message}", NotificationType.Error);
            return;
        }

        try
        {
            ServerBackupInfo backup;
            using (var progressDialog = _ui.ShowServerBackupProgress(serverName))
            {
                backup = await _backupService.CreateBackupAsync(
                    serverName,
                    destinationPath: destinationPath,
                    progress: progressDialog.Progress);
            }

            Logger.Information("伺服器「{Name}」備份建立成功：{File}", serverName, backup.FullPath);
            _ui.Notify($"已成功建立伺服器「{serverName}」備份：{backup.FileName}", NotificationType.Success);
            await _list.RefreshServersAsync();
        }
        catch (OperationCanceledException)
        {
            Logger.Information("使用者取消了伺服器「{Name}」的備份操作", serverName);
            _ui.Notify($"已取消備份「{serverName}」", NotificationType.Info);
        }
    }, "備份伺服器失敗", Logger);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task RestoreBackupAsync() => _list.RunForSelectedServerAsync(async selected =>
    {
        string serverName = selected.Name;

        var vm = new RestoreBackupViewModel(
            _backupService,
            serverName,
            _ui,
            selected.BackupPath,
            // 每次還原前即時查詢，避免對話框開啟期間伺服器已啟動仍誤判為停止
            isServerRunningCheck: () => _runtimeHost.IsRunning(serverName));
        if (await _ui.ShowRestoreBackupAsync(vm) == true)
        {
            Logger.Information("伺服器「{Name}」備份已成功還原", serverName);
            await _list.RefreshAndSelectServerAsync(serverName);
        }
    }, "還原備份失敗", Logger);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task OpenBackupFolderAsync() => _list.RunForSelectedServerAsync(async selected =>
    {
        string? backupFolder = selected.BackupPath;
        if (string.IsNullOrWhiteSpace(backupFolder) || !await _fileSystem.DirectoryExistsAsync(backupFolder))
        {
            bool isConfigured = !string.IsNullOrWhiteSpace(backupFolder);
            string message = isConfigured
                ? $"伺服器「{selected.Name}」的備份資料夾不存在：\n{backupFolder}\n\n是否要重新設定外部備份資料夾？"
                : $"伺服器「{selected.Name}」尚未設定自訂備份路徑。\n\n是否要立即設定外部備份資料夾？";
            if (await _ui.ConfirmAsync(message, isConfigured ? "備份資料夾不存在" : "尚未設定備份資料夾"))
            {
                await EditBackupPathAsync();
            }

            return;
        }

        _ui.OpenFolderOrWarn(_launcher, backupFolder);
    }, "開啟備份資料夾失敗", Logger);

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task EditBackupPathAsync() => _list.RunForSelectedServerAsync(
        selected => EditBackupPathCoreAsync(selected.Name),
        "更新備份資料夾路徑失敗",
        Logger);

    private async Task EditBackupPathCoreAsync(string serverName)
    {
        if (await _ui.GetServerOrWarnAsync(_serverManager, serverName) is not { } config)
        {
            return;
        }

        while (true)
        {
            string? initialFolder = await _fileSystem.DirectoryExistsAsync(config.BackupPath) ? config.BackupPath : null;
            string? folder = await _ui.PickFolderAsync($"選擇伺服器「{serverName}」的外部備份資料夾", initialFolder);
            if (string.IsNullOrWhiteSpace(folder))
            {
                return;
            }

            string chosen = folder.Trim();
            if (await _backupService.ValidateBackupDestinationAsync(chosen) is { } invalidReason)
            {
                _ui.ShowNotification(invalidReason, "備份路徑無效，請重新選擇", NotificationType.Warning);
                continue;
            }

            var updated = config.WithBackupPath(chosen);
            await _list.UpdateSelectedServerConfigAsync(
                _ => updated,
                $"已更新「{config.Name.Value}」備份資料夾路徑為：{chosen}",
                "更新備份資料夾路徑失敗",
                Logger);
            return;
        }
    }
}
