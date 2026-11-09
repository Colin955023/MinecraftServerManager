using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器管理頁：建立備份、還原備份與外部備份資料夾設定
/// </summary>
public sealed partial class ServerBackupViewModel : ViewModelBase, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerBackupViewModel));

    private readonly IUiService _ui;
    private readonly IServerManager _serverManager;
    private readonly IServerBackupService _backupService;
    private readonly IServerRuntime _serverRuntime;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IExternalLauncher _launcher;
    private readonly ServerListViewModel _list;

    public ServerBackupViewModel(
        IServerManager serverManager,
        IServerBackupService backupService,
        IServerRuntime serverRuntime,
        ILocalFileSystem fileSystem,
        ServerListViewModel list,
        IUiService uiService,
        IExternalLauncher launcher)
    {
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(backupService);
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(list);

        _ui = uiService;
        _serverManager = serverManager;
        _backupService = backupService;
        _serverRuntime = serverRuntime;
        _fileSystem = fileSystem;
        _launcher = launcher;
        _list = list;
        _list.SelectionStateChanged += OnSelectionStateChanged;
    }

    public void Dispose() => _list.SelectionStateChanged -= OnSelectionStateChanged;

    private bool HasSelectedServer() => _list.HasSelectedServer;

    private void OnSelectionStateChanged()
    {
        BackupServerCommand.NotifyCanExecuteChanged();
        RestoreBackupCommand.NotifyCanExecuteChanged();
        OpenBackupFolderCommand.NotifyCanExecuteChanged();
        EditBackupPathCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task BackupServer()
    {
        if (_list.SelectedServer is not { } selected)
        {
            return;
        }

        string serverName = selected.Name;

        if (string.IsNullOrWhiteSpace(selected.BackupPath))
        {
            _ui.ShowNotification("伺服器尚未設定外部備份資料夾，請先設定儲存位置", "請設定備份路徑", NotificationType.Warning);
            await EditBackupPath();
            selected = _list.SelectedServer ?? selected;
            if (string.IsNullOrWhiteSpace(selected.BackupPath))
            {
                return;
            }
        }

        string destinationDir = selected.BackupPath;
        if (_backupService.ValidateBackupDestination(destinationDir) is { } boundaryViolation)
        {
            _ui.ShowNotification(boundaryViolation, "備份路徑無效，請重新設定", NotificationType.Warning);
            await EditBackupPath();
            selected = _list.SelectedServer ?? selected;
            if (string.IsNullOrWhiteSpace(selected.BackupPath) || _backupService.ValidateBackupDestination(selected.BackupPath) is not null)
            {
                return;
            }

            destinationDir = selected.BackupPath;
        }

        string destinationPath;
        try
        {
            destinationPath = _backupService.PrepareBackupFilePath(serverName, destinationDir);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "建立備份目錄失敗：{Message}", ex.Message);
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
                    progress: progressDialog.Progress).ConfigureAwait(true);
            }

            Logger.Information("伺服器「{Name}」備份建立成功: {File}", serverName, backup.FullPath);
            _ui.Notify($"已成功建立伺服器「{serverName}」備份：{backup.FileName}", NotificationType.Success);
            await _list.RefreshServers();
        }
        catch (OperationCanceledException)
        {
            Logger.Information("使用者取消了伺服器「{Name}」的備份操作", serverName);
            _ui.Notify($"已取消備份「{serverName}」", NotificationType.Info);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "備份伺服器失敗: {Message}", ex.Message);
            _ui.Notify($"備份伺服器失敗：{ex.Message}", NotificationType.Error);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task RestoreBackup()
    {
        if (_list.SelectedServer is not { } selected)
        {
            return;
        }

        string serverName = selected.Name;

        var vm = new RestoreBackupViewModel(
            _backupService,
            serverName,
            _ui,
            selected.BackupPath,
            // 每次還原前即時查詢，避免對話框開啟期間伺服器已啟動仍誤判為停止
            isServerRunningCheck: () => _serverRuntime.IsRunning &&
                string.Equals(_serverRuntime.ActiveServerName, serverName, StringComparison.OrdinalIgnoreCase));
        if (await _ui.ShowRestoreBackupAsync(vm) == true)
        {
            Logger.Information("伺服器「{Name}」備份已成功還原", serverName);
            await _list.RefreshAndSelectServerAsync(serverName).ConfigureAwait(true);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task OpenBackupFolder()
    {
        if (_list.SelectedServer is not { } selected)
        {
            return;
        }

        string? backupFolder = selected.BackupPath;
        if (string.IsNullOrWhiteSpace(backupFolder) || !_fileSystem.DirectoryExists(backupFolder))
        {
            if (await _ui.ConfirmAsync(
                $"伺服器「{selected.Name}」尚未設定自訂備份路徑。\n\n是否要立即設定外部備份資料夾？",
                "尚未設定備份資料夾"))
            {
                await EditBackupPath();
            }

            return;
        }

        if (!_launcher.OpenFolder(backupFolder))
        {
            _ui.Notify($"無法開啟備份資料夾：{backupFolder}", NotificationType.Warning);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task EditBackupPath()
    {
        if (_list.SelectedServer is not { } selected)
        {
            return;
        }

        var config = await _serverManager.GetServerAsync(selected.Name);
        if (config is null)
        {
            return;
        }

        while (true)
        {
            string? initialFolder = _fileSystem.DirectoryExists(config.BackupPath) ? config.BackupPath : null;
            string? folder = await _ui.PickFolderAsync($"選擇伺服器「{selected.Name}」的外部備份資料夾", initialFolder);
            if (string.IsNullOrWhiteSpace(folder))
            {
                return;
            }

            string chosen = folder.Trim();
            if (_backupService.ValidateBackupDestination(chosen) is { } invalidReason)
            {
                _ui.ShowNotification(invalidReason, "備份路徑無效，請重新選擇", NotificationType.Warning);
                continue;
            }

            var updated = config.WithBackupPath(chosen);

            var res = await _serverManager.UpdateServerAsync(updated);
            if (res.Success)
            {
                _ui.Notify($"已更新「{config.Name.Value}」備份資料夾路徑為：{chosen}", NotificationType.Success);
                await _list.RefreshAndSelectServerAsync(config.Name.Value);
            }
            else
            {
                _ui.Notify($"更新備份資料夾路徑失敗：{res.Message}", NotificationType.Error);
            }

            return;
        }
    }
}
