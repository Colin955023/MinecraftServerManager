using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器列表項目模型。
/// </summary>
public sealed class ServerRowItem
{
    public string Name { get; init; } = string.Empty;

    public string Version { get; init; } = string.Empty;

    public string Loader { get; init; } = string.Empty;

    public string Status { get; init; } = "已停止";

    public string Size { get; init; } = "-";

    public string BackupStatus { get; init; } = "無備份";

    public string Path { get; init; } = string.Empty;

    public int MemoryMaxMb { get; init; } = 2048;

    public int? MemoryMinMb { get; init; }

    public string BackupPath { get; init; } = string.Empty;
}

/// <summary>
/// 管理伺服器頁面 ViewModel
/// </summary>
public sealed partial class ManageServerViewModel : PageViewModel
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ManageServer");

    private readonly SettingsManager? _settingsManager;
    private readonly IServerManager? _serverManager;
    private readonly IServerBackupService? _backupService;
    private readonly IServerRuntime? _serverRuntime;
    private readonly IServerInspector? _serverInspector;
    private readonly IServerLaunchPlanner? _launchPlanner;
    private readonly IServerPropertiesStore? _propertiesStore;
    private readonly IJavaRuntimeDetector? _javaDetector;
    private readonly IMinecraftJavaRequirementService? _javaRequirementService;
    private readonly IExternalLauncher? _launcher;
    private readonly Action<string>? _navigateCallback;
    private readonly Action<string, bool>? _notificationSink;

    [ObservableProperty]
    private string _detectPath = string.Empty;

    [ObservableProperty]
    private ServerRowItem? _selectedServer;

    [ObservableProperty]
    private string _selectedServerInfo = "選擇一個伺服器以查看詳細資訊";

    [ObservableProperty]
    private bool _isBackupInProgress;

    [ObservableProperty]
    private string _backupProgressText = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(MonitorServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(ConfigureServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(OpenServerFolderCommand))]
    [NotifyCanExecuteChangedFor(nameof(BackupServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(RestoreBackupCommand))]
    [NotifyCanExecuteChangedFor(nameof(DeleteServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(EditServerMemoryCommand))]
    [NotifyCanExecuteChangedFor(nameof(RecheckServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(OpenBackupFolderCommand))]
    [NotifyCanExecuteChangedFor(nameof(EditBackupPathCommand))]
    private bool _hasSelectedServer;

    public ManageServerViewModel(
        SettingsManager? settingsManager = null,
        IServerManager? serverManager = null,
        IServerBackupService? backupService = null,
        IServerRuntime? serverRuntime = null,
        IServerInspector? serverInspector = null,
        IServerLaunchPlanner? launchPlanner = null,
        IServerPropertiesStore? propertiesStore = null,
        Action<string>? navigateCallback = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null,
        IJavaRuntimeDetector? javaDetector = null,
        IMinecraftJavaRequirementService? javaRequirementService = null)
        : base("manage", "管理現有伺服器", "檢視已安裝伺服器清單，進行啟動、停止、設定與備份維護")
    {
        _settingsManager = settingsManager;
        _serverManager = serverManager;
        _backupService = backupService;
        _serverRuntime = serverRuntime;
        _serverInspector = serverInspector ?? new ServerInspector();
        _launchPlanner = launchPlanner ?? new ServerLaunchPlanner();
        _propertiesStore = propertiesStore;
        _navigateCallback = navigateCallback;
        _notificationSink = notificationSink;
        _launcher = launcher;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;

        _detectPath = ResolveServersDirectory();
        Servers = [];
    }

    public ObservableCollection<ServerRowItem> Servers { get; }

    private string ResolveServersDirectory()
    {
        if (_settingsManager is null)
        {
            return string.Empty;
        }

        try
        {
            return _settingsManager.GetValidatedServersRootPath();
        }
        catch
        {
            return _settingsManager.GetServersRoot();
        }
    }

    partial void OnSelectedServerChanged(ServerRowItem? value)
    {
        HasSelectedServer = value is not null;
        if (value is not null)
        {
            string minText = value.MemoryMinMb.HasValue ? $"{value.MemoryMinMb.Value} MB" : "未設定";
            SelectedServerInfo = $"已選取伺服器：{value.Name} ({value.Version} / {value.Loader}) — 狀態：{value.Status} | 記憶體：最小 {minText} / 最大 {value.MemoryMaxMb} MB";
        }
        else
        {
            SelectedServerInfo = "選擇一個伺服器以查看詳細資訊";
        }
    }

    [RelayCommand]
    public async Task DetectServers()
    {
        if (_serverManager is null)
        {
            await RefreshServers();
            return;
        }

        try
        {
            var report = await _serverManager.ScanAndRegisterAsync();
            await RefreshServers();
            _notificationSink?.Invoke(
                $"偵測完成：已管理 {report.AlreadyManaged} 個，新增 {report.NewlyAdded} 個，跳過 {report.Skipped} 個",
                false);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "偵測現有伺服器失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"偵測現有伺服器失敗：{ex.Message}", true);
        }
    }

    [RelayCommand]
    public void AddServer() => _navigateCallback?.Invoke("create");

    [RelayCommand]
    public async Task RefreshServers()
    {
        DetectPath = ResolveServersDirectory();
        if (_serverManager is not null)
        {
            try
            {
                var serverEntries = await _serverManager.GetAllServersAsync();
                Servers.Clear();
                foreach (var s in serverEntries)
                {
                    string size = FormatDirectorySize(s.Path);
                    string backupStatus = "無備份";
                    try
                    {
                        if (!string.IsNullOrWhiteSpace(s.BackupPath) && Directory.Exists(s.BackupPath))
                        {
                            var archives = Directory.EnumerateFiles(s.BackupPath, "*.zip").ToList();
                            if (archives.Count > 0)
                            {
                                DateTime latest = archives.Max(f => new FileInfo(f).LastWriteTime);
                                backupStatus = $"{archives.Count} 個備份（{FormatRelativeTime(latest)}）";
                            }
                        }
                    }
                    catch
                    {
                    }

                    bool isThisServerRunning = _serverRuntime?.IsRunning == true &&
                        string.Equals(_serverRuntime.ActiveServerName, s.Name.Value, StringComparison.OrdinalIgnoreCase);

                    Servers.Add(new ServerRowItem
                    {
                        Name = s.Name.Value,
                        Version = s.MinecraftVersion.Value,
                        Loader = s.LoaderType.ToString(),
                        Status = isThisServerRunning ? "執行中" : "已停止",
                        Size = size,
                        BackupStatus = backupStatus,
                        Path = s.Path,
                        MemoryMaxMb = s.MemoryMaxMb,
                        MemoryMinMb = s.MemoryMinMb,
                        BackupPath = s.BackupPath
                    });
                }
                Logger.Information("成功重新整理伺服器清單，共 {Count} 個伺服器，路徑: {Path}", Servers.Count, DetectPath);
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "載入伺服器清單失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"載入伺服器清單失敗：{ex.Message}", true);
                return;
            }
        }
    }

    /// <summary>
    /// 重新整理伺服器清單並選取指定名稱之伺服器
    /// </summary>
    public async Task RefreshAndSelectServerAsync(string serverName)
    {
        await RefreshServers();
        var target = Servers.FirstOrDefault(s => string.Equals(s.Name, serverName, StringComparison.OrdinalIgnoreCase));
        if (target is not null)
        {
            SelectedServer = target;
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task StartServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_serverRuntime is not null && _serverManager is not null)
        {
            try
            {
                var server = await _serverManager.GetServerAsync(SelectedServer.Name);
                if (server is not null)
                {
                    // 透過 ServerInspector 與 ServerLaunchPlanner 建立強型別啟動計畫
                    var inspection = await _serverInspector!.InspectAsync(server.Path).ConfigureAwait(true);

                    // 驗證啟動目標確實存在，避免子程序瞬間閃退
                    string? missingTarget = ResolveMissingLaunchTarget(server.Path, inspection.LaunchTarget.Value);
                    if (missingTarget is not null)
                    {
                        Logger.Error("啟動目標檔案不存在: {Target}", missingTarget);
                        _notificationSink?.Invoke($"無法啟動：找不到啟動檔案「{missingTarget}」，請重新匯入或重建此伺服器", true);
                        return;
                    }

                    // 精準解析該 Minecraft 版本所需的 Java 實體執行檔
                    var (javaPath, javaError) = await ResolveJavaExecutableAsync(server.MinecraftVersion.Value).ConfigureAwait(true);
                    if (javaError is not null)
                    {
                        Logger.Error("解析 Java 執行環境失敗: {Message}", javaError);
                        _notificationSink?.Invoke(javaError, true);
                        return;
                    }

                    var plan = _launchPlanner!.CreatePlan(server, inspection, javaPath);

                    await _serverRuntime.StartAsync(plan).ConfigureAwait(true);

                    // 啟動後偵測是否於 3 秒內異常退出
                    string? earlyExit = await DetectEarlyExitAsync().ConfigureAwait(true);
                    if (earlyExit is not null)
                    {
                        Logger.Error("伺服器啟動後異常退出: {Message}", earlyExit);
                        _notificationSink?.Invoke(earlyExit, true);
                        await RefreshServers();
                        return;
                    }

                    SelectedServer = new ServerRowItem
                    {
                        Name = SelectedServer.Name,
                        Version = SelectedServer.Version,
                        Loader = SelectedServer.Loader,
                        Status = "執行中",
                        Size = SelectedServer.Size,
                        BackupStatus = SelectedServer.BackupStatus,
                        Path = SelectedServer.Path
                    };
                    Logger.Information("伺服器已成功啟動: {Name} (版本: {Version})", server.Name.Value, server.MinecraftVersion.Value);
                    _notificationSink?.Invoke($"伺服器「{server.Name.Value}」已依據啟動計畫成功啟動", false);
                    return;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "啟動伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"啟動伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"啟動伺服器「{SelectedServer.Name}」", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task StopServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_serverRuntime is not null && _serverRuntime.IsRunning)
        {
            try
            {
                await _serverRuntime.StopAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(true);
                SelectedServer = new ServerRowItem
                {
                    Name = SelectedServer.Name,
                    Version = SelectedServer.Version,
                    Loader = SelectedServer.Loader,
                    Status = "已停止",
                    Size = SelectedServer.Size,
                    BackupStatus = SelectedServer.BackupStatus,
                    Path = SelectedServer.Path
                };
                Logger.Information("伺服器已成功停止: {Name}", SelectedServer.Name);
                _notificationSink?.Invoke($"已成功停止伺服器「{SelectedServer.Name}」", false);
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "停止伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"停止伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"停止伺服器「{SelectedServer.Name}」", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void MonitorServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_serverRuntime is not null)
        {
            var vm = new ServerMonitorViewModel(
                _serverRuntime,
                SelectedServer.Name,
                SelectedServer.Path,
                SelectedServer.Version,
                startRequestHandler: StartServer);
            var win = new ServerMonitorWindow(vm);
            win.Show();
            return;
        }

        _notificationSink?.Invoke($"開啟伺服器「{SelectedServer.Name}」主控台與效能監控", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void ConfigureServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        var store = _propertiesStore ?? (!string.IsNullOrWhiteSpace(_settingsManager?.GetServersRoot()) ? new ServerPropertiesStore(_settingsManager.GetServersRoot()) : null);
        if (store is not null)
        {
            var vm = new ServerPropertiesViewModel(store, SelectedServer.Name);
            var dialog = new ServerPropertiesDialog(vm);
            if (dialog.ShowDialog() == true)
            {
                _notificationSink?.Invoke($"伺服器「{SelectedServer.Name}」屬性設定已更新", false);
            }
            return;
        }

        _notificationSink?.Invoke($"開啟伺服器「{SelectedServer.Name}」設定", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void OpenServerFolder()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (!Directory.Exists(SelectedServer.Path))
        {
            _notificationSink?.Invoke($"資料夾不存在：{SelectedServer.Path}", true);
            return;
        }

        if (_launcher is not null)
        {
            if (!_launcher.OpenFolder(SelectedServer.Path))
            {
                _notificationSink?.Invoke($"無法開啟資料夾：{SelectedServer.Path}", true);
            }
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task BackupServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        var saveDialog = new Microsoft.Win32.SaveFileDialog
        {
            Title = $"請選擇伺服器「{SelectedServer.Name}」的備份儲存檔案路徑",
            Filter = "ZIP 壓縮檔 (*.zip)|*.zip",
            FileName = $"backup-{SelectedServer.Name}-{DateTime.Now:yyyyMMdd-HHmmss}.zip"
        };

        if (!string.IsNullOrWhiteSpace(SelectedServer.BackupPath) && Directory.Exists(SelectedServer.BackupPath))
        {
            saveDialog.InitialDirectory = SelectedServer.BackupPath;
        }

        if (saveDialog.ShowDialog() != true)
        {
            return;
        }

        // 於 await 之前快取選取伺服器資料副本，杜絕非同步期間 SelectedServer 變更造成的 NRE
        string serverName = SelectedServer.Name;

        string? boundaryViolation = ValidateBackupDestination(saveDialog.FileName);
        if (boundaryViolation is not null)
        {
            Logger.Warning("備份路徑越界遭阻擋: {Path}", saveDialog.FileName);
            _notificationSink?.Invoke(boundaryViolation, true);
            return;
        }

        if (_backupService is not null)
        {
            var progressDialog = new ServerBackupProgressDialog(serverName)
            {
                Owner = Application.Current?.MainWindow
            };

            progressDialog.Show();

            try
            {
                var backup = await Task.Run(async () =>
                {
                    return await _backupService.CreateBackupAsync(
                        serverName,
                        destinationPath: saveDialog.FileName,
                        progress: progressDialog.Progress).ConfigureAwait(false);
                });

                var config = _serverManager is null ? null : await _serverManager.GetServerAsync(serverName);
                if (config is not null && _serverManager is not null)
                {
                    string backupDir = Path.GetDirectoryName(backup.FullPath) ?? string.Empty;
                    var updated = new ServerConfig(
                        config.Name,
                        config.MinecraftVersion,
                        config.LoaderType,
                        config.LoaderVersion,
                        config.MemoryMaxMb,
                        config.MemoryMinMb,
                        config.Path,
                        config.JvmArgs,
                        backupDir);

                    await _serverManager.UpdateServerAsync(updated);
                }

                ServerBackupProgressDialog.MarkCompleted();
                progressDialog.Close();
                Logger.Information("伺服器「{Name}」備份建立成功: {File}", serverName, backup.FullPath);
                _notificationSink?.Invoke($"已成功建立伺服器「{serverName}」備份：{backup.FileName}", false);
                await RefreshServers();
                return;
            }
            catch (OperationCanceledException)
            {
                ServerBackupProgressDialog.MarkCompleted();
                progressDialog.Close();
                Logger.Information("使用者取消了伺服器「{Name}」的備份操作", serverName);
                _notificationSink?.Invoke($"已取消備份「{serverName}」", true);
                return;
            }
            catch (Exception ex)
            {
                ServerBackupProgressDialog.MarkCompleted();
                progressDialog.Close();
                Logger.Error(ex, "備份伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"備份伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"建立伺服器「{serverName}」備份", false);
    }

    /// <summary>
    /// 備份目的地邊界檢查：禁止落在 servers 根目錄或任一伺服器子資料夾內。
    /// </summary>
    /// <returns>合法時回傳 null，違規時回傳阻擋訊息。</returns>
    private string? ValidateBackupDestination(string destinationFile)
    {
        string serversRoot = ResolveServersDirectory();
        if (string.IsNullOrWhiteSpace(serversRoot))
        {
            return null;
        }

        try
        {
            string targetDir = Path.GetFullPath(Path.GetDirectoryName(destinationFile) ?? destinationFile);
            string rootDir = Path.GetFullPath(serversRoot);

            if (string.Equals(targetDir.TrimEnd(Path.DirectorySeparatorChar), rootDir.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            {
                return "備份檔案不可存放於 servers 根目錄，請另選其他位置";
            }

            string rootPrefix = rootDir.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (targetDir.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
            {
                return "備份檔案不可存放於任何伺服器資料夾內，請另選 servers 目錄以外的位置";
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void RestoreBackup()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_backupService is not null)
        {
            bool isRunning = _serverRuntime?.IsRunning == true &&
                string.Equals(_serverRuntime.ActiveServerName, SelectedServer.Name, StringComparison.OrdinalIgnoreCase);

            var vm = new RestoreBackupViewModel(
                _backupService,
                SelectedServer.Name,
                SelectedServer.BackupPath,
                isServerRunningCheck: () => isRunning);
            var dialog = new RestoreBackupDialog(vm);
            if (dialog.ShowDialog() == true)
            {
                Logger.Information("伺服器「{Name}」備份已成功還原", SelectedServer.Name);
                _notificationSink?.Invoke($"伺服器「{SelectedServer.Name}」備份已安全還原", false);
            }
            return;
        }

        _notificationSink?.Invoke($"還原伺服器「{SelectedServer.Name}」備份", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task DeleteServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        string name = SelectedServer.Name;
        string backupPath = SelectedServer.BackupPath;
        var currentServer = SelectedServer;

        int backupCount = 0;
        IReadOnlyList<ServerBackupInfo>? backupsToDelete = null;
        if (_backupService is not null)
        {
            try
            {
                var backups = await _backupService.ListBackupsAsync(name, backupPath);
                backupCount = backups.Count;
                backupsToDelete = backups;
            }
            catch
            {
            }
        }

        ServerDeleteDecision decision = ServerDeleteDecision.DeleteServerOnly;
        if (Application.Current is not null)
        {
            var dialog = new ServerDeleteConfirmationDialog(name, backupCount);
            if (Application.Current.MainWindow is not null)
            {
                dialog.Owner = Application.Current.MainWindow;
            }

            if (dialog.ShowDialog() != true || dialog.Decision == ServerDeleteDecision.Cancel)
            {
                return;
            }
            decision = dialog.Decision;
        }

        if (_serverManager is not null)
        {
            try
            {
                if (decision == ServerDeleteDecision.DeleteServerAndBackups && _backupService is not null && backupsToDelete is { Count: > 0 })
                {
                    try
                    {
                        foreach (var b in backupsToDelete)
                        {
                            await _backupService.DeleteBackupAsync(name, b.FileName, backupPath);
                        }
                        Logger.Information("伺服器「{Name}」的 {Count} 個備份檔案已一併刪除", name, backupsToDelete.Count);
                    }
                    catch (Exception ex)
                    {
                        Logger.Warning("刪除伺服器「{Name}」的備份檔案時發生錯誤: {Error}", name, ex.Message);
                    }
                }

                var result = await _serverManager.DeleteServerAsync(name);
                if (result.Success)
                {
                    Servers.Remove(currentServer);
                    SelectedServer = null;
                    Logger.Information("伺服器「{Name}」已成功刪除", name);
                    _notificationSink?.Invoke($"已成功刪除伺服器「{name}」", false);
                    return;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "刪除伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"刪除伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"刪除伺服器「{name}」", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task EditServerMemory()
    {
        if (SelectedServer is null || _serverManager is null)
        {
            return;
        }

        var config = await _serverManager.GetServerAsync(SelectedServer.Name);
        if (config is null)
        {
            return;
        }

        var vm = new ServerMemoryViewModel(config, async (max, min) =>
        {
            var updated = new ServerConfig(
                config.Name,
                config.MinecraftVersion,
                config.LoaderType,
                config.LoaderVersion,
                max,
                min,
                config.Path,
                config.JvmArgs,
                config.BackupPath);

            var res = await _serverManager.UpdateServerAsync(updated);
            return res.Success;
        });

        var dialog = new ServerMemoryDialog(vm);
        if (dialog.ShowDialog() == true)
        {
            _notificationSink?.Invoke($"已更新伺服器「{SelectedServer.Name}」記憶體設定", false);
            await RefreshAndSelectServerAsync(SelectedServer.Name);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task RecheckServer()
    {
        if (SelectedServer is null || _serverManager is null)
        {
            return;
        }

        var config = await _serverManager.GetServerAsync(SelectedServer.Name);
        if (config is null)
        {
            return;
        }

        try
        {
            var inspection = await _serverInspector!.InspectAsync(SelectedServer.Path);
            if (!inspection.IsCandidate)
            {
                _notificationSink?.Invoke("重新檢測失敗：目錄不包含有效的 Minecraft 伺服器檔案", true);
                return;
            }

            var lk = Enum.TryParse<LoaderKind>(inspection.LoaderType, ignoreCase: true, out var parsedLk) ? parsedLk : config.LoaderType;
            var mv = MinecraftVersion.TryParse(inspection.MinecraftVersion, out var parsedMv) ? parsedMv : config.MinecraftVersion;

            var updated = new ServerConfig(
                config.Name,
                mv,
                lk,
                inspection.LoaderVersion ?? config.LoaderVersion,
                config.MemoryMaxMb,
                config.MemoryMinMb,
                config.Path,
                config.JvmArgs,
                config.BackupPath);

            await _serverManager.UpdateServerAsync(updated);
            await RefreshAndSelectServerAsync(config.Name.Value);

            NotificationDialog.Show(
                null,
                "重新檢測完成",
                $"已重新檢測伺服器：{config.Name.Value}\nMinecraft 版本：{mv.Value}\n載入器類型：{lk}\n載入器版本：{updated.LoaderVersion}",
                NotificationLevel.Info);
        }
        catch (Exception ex)
        {
            _notificationSink?.Invoke($"重新檢測失敗：{ex.Message}", true);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task OpenBackupFolder()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(SelectedServer.BackupPath) || !Directory.Exists(SelectedServer.BackupPath))
        {
            if (DialogHelper.Confirm(
                $"伺服器「{SelectedServer.Name}」尚未設定自訂備份路徑。\n\n是否要立即設定外部備份資料夾？",
                "尚未設定備份資料夾"))
            {
                await EditBackupPath();
            }
            return;
        }

        if (_launcher is not null)
        {
            if (!_launcher.OpenFolder(SelectedServer.BackupPath))
            {
                _notificationSink?.Invoke($"無法開啟備份資料夾：{SelectedServer.BackupPath}", true);
            }
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task EditBackupPath()
    {
        if (SelectedServer is null || _serverManager is null)
        {
            return;
        }

        var config = await _serverManager.GetServerAsync(SelectedServer.Name);
        if (config is null)
        {
            return;
        }

        var dialog = new Microsoft.Win32.OpenFolderDialog
        {
            Title = $"選擇伺服器「{SelectedServer.Name}」的外部備份資料夾",
            Multiselect = false
        };

        if (!string.IsNullOrWhiteSpace(config.BackupPath) && Directory.Exists(config.BackupPath))
        {
            dialog.InitialDirectory = config.BackupPath;
        }

        if (dialog.ShowDialog() == true && !string.IsNullOrWhiteSpace(dialog.FolderName))
        {
            string selected = dialog.FolderName.Trim();
            string? invalidReason = ValidateBackupDestination(selected);
            if (invalidReason is not null)
            {
                DialogHelper.ShowWarning(invalidReason, "備份路徑無效");
                _notificationSink?.Invoke(invalidReason, true);
                return;
            }

            var updated = new ServerConfig(
                config.Name,
                config.MinecraftVersion,
                config.LoaderType,
                config.LoaderVersion,
                config.MemoryMaxMb,
                config.MemoryMinMb,
                config.Path,
                config.JvmArgs,
                selected);

            var res = await _serverManager.UpdateServerAsync(updated);
            if (res.Success)
            {
                _notificationSink?.Invoke($"已更新「{config.Name.Value}」備份資料夾路徑為：{selected}", false);
                await RefreshAndSelectServerAsync(config.Name.Value);
            }
            else
            {
                _notificationSink?.Invoke($"更新備份資料夾路徑失敗：{res.Message}", true);
            }
        }
    }

    /// <summary>
    /// 驗證啟動 JAR 或腳本是否確實存在，存在則回傳 null，缺失則回傳檔名。
    /// </summary>
    private static string? ResolveMissingLaunchTarget(string serverPath, string launchTarget)
    {
        string target = string.IsNullOrWhiteSpace(launchTarget) ? "server.jar" : launchTarget.Trim();
        try
        {
            string fullPath = Path.GetFullPath(Path.Combine(serverPath, target));
            return File.Exists(fullPath) ? null : target;
        }
        catch
        {
            return target;
        }
    }

    /// <summary>
    /// 依據 Minecraft 版本精準解析所需的 Java 實體執行檔路徑。
    /// </summary>
    /// <returns>成功時回傳 (路徑, null)；失敗時回傳 (null, 錯誤訊息)。</returns>
    private async Task<(string? JavaPath, string? Error)> ResolveJavaExecutableAsync(string minecraftVersion)
    {
        if (_javaDetector is null)
        {
            // 未注入偵測器時維持既有行為，交由 ServerLaunchPlanner 處理
            return (null, null);
        }

        int requiredMajor;
        try
        {
            requiredMajor = _javaRequirementService is not null
                ? await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion).ConfigureAwait(true)
                : 17;
        }
        catch (Exception exception)
        {
            Logger.Warning("查詢 Minecraft {Version} 所需 Java 版本失敗（{Message}），改用預設值 17", minecraftVersion, exception.Message);
            requiredMajor = 17;
        }

        JavaRuntimeInfo? runtime;
        try
        {
            runtime = await _javaDetector.FindBestMatchAsync(requiredMajor).ConfigureAwait(true);
        }
        catch (Exception exception)
        {
            return (null, $"偵測 Java {requiredMajor} 執行環境時發生錯誤：{exception.Message}");
        }

        if (runtime is null)
        {
            return (null, $"本機未安裝 Minecraft {minecraftVersion} 所需的 Java {requiredMajor}，請至「建立伺服器」頁面透過 winget 安裝後再啟動");
        }

        Logger.Information(
            "已解析 Minecraft {Version} 的 Java 執行檔: {Path} (major {Major})",
            minecraftVersion,
            runtime.ExecutablePath,
            runtime.MajorVersion);

        return (runtime.ExecutablePath, null);
    }

    /// <summary>
    /// 啟動後等待 3 秒，若子程序已異常退出則回傳錯誤訊息。
    /// </summary>
    private async Task<string?> DetectEarlyExitAsync()
    {
        if (_serverRuntime is null)
        {
            return null;
        }

        await Task.Delay(TimeSpan.FromSeconds(3)).ConfigureAwait(true);

        if (_serverRuntime.IsRunning)
        {
            return null;
        }

        int exitCode = _serverRuntime.ExitCode ?? -1;
        return exitCode == 0
            ? null
            : $"伺服器啟動後立即結束（結束代碼 {exitCode}），請開啟監控主控台查看詳細輸出以確認原因";
    }

    /// <summary>
    /// 將最後備份時間格式化為相對時間描述。
    /// </summary>
    private static string FormatRelativeTime(DateTime timestamp)
    {
        var span = DateTime.Now - timestamp;
        if (span < TimeSpan.Zero)
        {
            span = TimeSpan.Zero;
        }

        return span.TotalMinutes switch
        {
            < 1 => "剛剛",
            < 60 => $"{(int)span.TotalMinutes} 分鐘前",
            _ => span.TotalHours < 24
                ? $"{(int)span.TotalHours} 小時前"
                : $"{(int)span.TotalDays} 天前"
        };
    }

    private static string FormatDirectorySize(string directoryPath)
    {
        if (string.IsNullOrWhiteSpace(directoryPath) || !Directory.Exists(directoryPath))
        {
            return "-";
        }

        try
        {
            long bytes = Directory.EnumerateFiles(directoryPath, "*", SearchOption.AllDirectories)
                .Sum(file =>
                {
                    try { return new FileInfo(file).Length; } catch { return 0L; }
                });

            return bytes switch
            {
                >= 1024L * 1024 * 1024 => $"{bytes / (1024.0 * 1024 * 1024):F2} GB",
                >= 1024L * 1024 => $"{bytes / (1024.0 * 1024):F2} MB",
                >= 1024L => $"{bytes / 1024.0:F2} KB",
                _ => $"{bytes} B"
            };
        }
        catch
        {
            return "-";
        }
    }
}
