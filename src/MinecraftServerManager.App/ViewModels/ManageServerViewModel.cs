using MinecraftServerManager.App.Services;
using System.Collections.ObjectModel;
using System.IO;
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
public sealed partial class ServerRowItem : ObservableObject
{
    public string Name { get; init; } = string.Empty;

    public string Version { get; init; } = string.Empty;

    public string Loader { get; init; } = string.Empty;

    public string Path { get; init; } = string.Empty;

    public int MemoryMaxMb { get; init; } = 2048;

    public int? MemoryMinMb { get; init; }

    public string BackupPath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Status { get; set; } = "已停止";

    [ObservableProperty]
    public partial bool HasMissingFiles { get; set; }

    [ObservableProperty]
    public partial string Size { get; set; } = "-";

    [ObservableProperty]
    public partial string BackupStatus { get; set; } = "無備份";

    [ObservableProperty]
    public partial string LastModified { get; set; } = "-";
}

/// <summary>
/// 管理伺服器頁面 ViewModel
/// </summary>
public sealed partial class ManageServerViewModel : PageViewModel, IDisposable
{
    private readonly IUiService _ui;

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
    private IMonitorWindow? _activeMonitorWindow;
    private ServerMonitorViewModel? _activeMonitorViewModel;

    [ObservableProperty]
    public partial string DetectPath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial ServerRowItem? SelectedServer { get; set; }

    [ObservableProperty]
    public partial string SelectedServerInfo { get; set; } = "選擇一個伺服器以檢視詳細資訊";

    [ObservableProperty]
    public partial bool IsBackupInProgress { get; set; }

    [ObservableProperty]
    public partial string BackupProgressText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsBusy { get; set; }

    [ObservableProperty]
    public partial string BusyStatusText { get; set; } = string.Empty;

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
    public partial bool HasSelectedServer { get; set; }

    public bool CanStartOrMonitorServer => HasSelectedServer && SelectedServer is not null && !SelectedServer.HasMissingFiles;

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
        IMinecraftJavaRequirementService? javaRequirementService = null,
        IUiService? uiService = null)
        : base("manage", "管理現有伺服器", "檢視已安裝伺服器清單，進行啟動、停止、設定與備份維護")
    {
        _ui = uiService ?? NoOpUiService.Instance;
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
        DetectPath = ResolveServersDirectory();
        Servers = [];

        if (_serverRuntime is not null)
        {
            _serverRuntime.ServerStarted += RequestStatusRefresh;
            _serverRuntime.ServerReady += RequestStatusRefresh;
            _serverRuntime.ServerExited += OnServerExitedHandler;
        }
    }

    private void OnServerExitedHandler(int exitCode) => RequestStatusRefresh();

    public void Dispose()
    {
        if (_serverRuntime is not null)
        {
            _serverRuntime.ServerStarted -= RequestStatusRefresh;
            _serverRuntime.ServerReady -= RequestStatusRefresh;
            _serverRuntime.ServerExited -= OnServerExitedHandler;
        }
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
            SelectedServerInfo = "選擇一個伺服器以檢視詳細資訊";
        }

        OnPropertyChanged(nameof(CanStartOrMonitorServer));
        StartServerCommand.NotifyCanExecuteChanged();
        MonitorServerCommand.NotifyCanExecuteChanged();
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

    /// <summary>
    /// 於 UI 執行緒排入伺服器狀態更新（不阻塞事件來源執行緒）
    /// </summary>
    private void RequestStatusRefresh() => _ui.PostToUi(() => { _ = UpdateServerStatusInPlaceAsync(); });

    [RelayCommand]
    public void AddServer() => _navigateCallback?.Invoke("create");

    [RelayCommand]
    public async Task RefreshServers()
    {
        IsBusy = true;
        BusyStatusText = "正在載入伺服器清單...";
        try
        {
            DetectPath = ResolveServersDirectory();
            if (_serverManager is not null)
            {
                try
                {
                    string? prevSelectedName = SelectedServer?.Name;
                    var serverEntries = await _serverManager.GetAllServersAsync();
                    bool runtimeRunning = _serverRuntime?.IsRunning == true;
                    string? activeName = _serverRuntime?.ActiveServerName;

                    // 目錄容量、備份掃描與檔案檢查屬於磁碟 I/O，於背景執行緒完成，UI 執行緒僅負責更新集合
                    IReadOnlyList<ServerRowSnapshot> snapshots = await Task.Run(() =>
                        serverEntries.Select(s => BuildServerSnapshot(s, runtimeRunning, activeName)).ToList())
                        .ConfigureAwait(true);

                    Servers.Clear();
                    foreach (ServerRowSnapshot snapshot in snapshots)
                    {
                        Servers.Add(ToRowItem(snapshot));
                    }

                    if (!string.IsNullOrEmpty(prevSelectedName))
                    {
                        SelectedServer = Servers.FirstOrDefault(x => string.Equals(x.Name, prevSelectedName, StringComparison.OrdinalIgnoreCase)) ?? Servers.FirstOrDefault();
                    }
                    else
                    {
                        SelectedServer = Servers.FirstOrDefault();
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
        finally
        {
            IsBusy = false;
            BusyStatusText = string.Empty;
        }
    }

    private sealed record ServerRowSnapshot(
        ServerConfig Config,
        string Size,
        string BackupStatus,
        string Status,
        string LastModified,
        bool HasMissingFiles);

    private sealed record ServerStatusProbe(string Status, bool HasMissingFiles, string? LastModified);

    private static ServerRowSnapshot BuildServerSnapshot(ServerConfig s, bool runtimeRunning, string? activeName)
    {
        bool isThisServerRunning = runtimeRunning && string.Equals(activeName, s.Name.Value, StringComparison.OrdinalIgnoreCase);
        ServerStatusProbe probe = ProbeServerStatus(s.Path, s.LoaderType.ToString(), isThisServerRunning);
        return new ServerRowSnapshot(
            Config: s,
            Size: FormatDirectorySize(s.Path),
            BackupStatus: BuildBackupStatus(s),
            Status: probe.Status,
            LastModified: probe.LastModified ?? "-",
            HasMissingFiles: probe.HasMissingFiles);
    }

    private static ServerRowItem ToRowItem(ServerRowSnapshot snapshot)
    {
        ServerConfig s = snapshot.Config;
        return new ServerRowItem
        {
            Name = s.Name.Value,
            Version = s.MinecraftVersion.Value,
            Loader = s.LoaderType.ToString(),
            Status = snapshot.Status,
            Size = snapshot.Size,
            BackupStatus = snapshot.BackupStatus,
            LastModified = snapshot.LastModified,
            Path = s.Path,
            MemoryMaxMb = s.MemoryMaxMb,
            MemoryMinMb = s.MemoryMinMb,
            BackupPath = s.BackupPath,
            HasMissingFiles = snapshot.HasMissingFiles,
        };
    }

    private static ServerStatusProbe ProbeServerStatus(string path, string loader, bool isRunning)
    {
        if (isRunning)
        {
            return new ServerStatusProbe("執行中", false, GetLastModifiedText(path));
        }

        var (hasMissing, missingFiles) = CheckImportantFiles(path, loader);
        string status = hasMissing ? $"缺少重要檔案：{string.Join("、", missingFiles)}" : "已停止";
        return new ServerStatusProbe(status, hasMissing, GetLastModifiedText(path));
    }

    private static string BuildBackupStatus(ServerConfig s)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(s.BackupPath) && Directory.Exists(s.BackupPath))
            {
                string prefix = $"backup-{s.Name.Value}-";
                var archives = Directory.EnumerateFiles(s.BackupPath, "*.zip")
                    .Where(f =>
                    {
                        string fn = Path.GetFileName(f);
                        return fn.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
                               fn.StartsWith($"{s.Name.Value}-", StringComparison.OrdinalIgnoreCase) ||
                               fn.Contains(s.Name.Value, StringComparison.OrdinalIgnoreCase);
                    })
                    .ToList();

                if (archives.Count > 0)
                {
                    DateTime latest = archives.Max(f => new FileInfo(f).LastWriteTime);
                    return $"{archives.Count} 個備份（{FormatRelativeTime(latest)}）";
                }
            }
        }
        catch
        {
        }

        return "無備份";
    }

    private static string? GetLastModifiedText(string path)
    {
        try
        {
            return Directory.Exists(path)
                ? Directory.GetLastWriteTime(path).ToString("yyyy/MM/dd HH:mm", System.Globalization.CultureInfo.InvariantCulture)
                : null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// 低資源消耗即時更新各伺服器的執行與重要檔案狀態：UI 執行緒僅讀寫集合，檔案檢查於背景執行，不重新掃描整個硬碟與目錄容量。
    /// </summary>
    public async Task UpdateServerStatusInPlaceAsync()
    {
        bool runtimeRunning = _serverRuntime?.IsRunning == true;
        string? activeName = _serverRuntime?.ActiveServerName;
        var targets = Servers.Select(s => (Row: s, s.Path, s.Loader, s.Name)).ToList();

        var probes = await Task.Run(() => targets
            .Select(t => ProbeServerStatus(
                t.Path,
                t.Loader,
                runtimeRunning && string.Equals(activeName, t.Name, StringComparison.OrdinalIgnoreCase)))
            .ToList()).ConfigureAwait(true);

        for (int i = 0; i < targets.Count; i++)
        {
            ServerRowItem row = targets[i].Row;
            row.Status = probes[i].Status;
            row.HasMissingFiles = probes[i].HasMissingFiles;
            if (probes[i].LastModified is { } lastModified)
            {
                row.LastModified = lastModified;
            }
        }

        if (SelectedServer is not null)
        {
            OnSelectedServerChanged(SelectedServer);
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

    [RelayCommand(CanExecute = nameof(CanStartOrMonitorServer))]
    public async Task StartServer()
    {
        if (SelectedServer is null || SelectedServer.HasMissingFiles)
        {
            return;
        }

        await StartServerByNameAsync(SelectedServer.Name);
    }

    /// <summary>
    /// 依據伺服器名稱精準啟動伺服器，不仰賴 DataGrid 選取項目
    /// </summary>
    public async Task<bool> StartServerByNameAsync(string serverName)
    {
        if (string.IsNullOrWhiteSpace(serverName))
        {
            return false;
        }

        if (_serverRuntime is null || _serverManager is null)
        {
            return false;
        }

        if (_serverRuntime.IsRunning)
        {
            _notificationSink?.Invoke("目前已有伺服器正在執行中，請先停止現有伺服器", true);
            return false;
        }

        try
        {
            var server = await _serverManager.GetServerAsync(serverName);
            if (server is null)
            {
                _notificationSink?.Invoke($"找不到伺服器「{serverName}」", true);
                return false;
            }

            var inspection = await _serverInspector!.InspectAsync(server.Path).ConfigureAwait(true);
            string? missingTarget = await Task.Run(() => ResolveMissingLaunchTarget(server.Path, inspection.LaunchTarget.Value)).ConfigureAwait(true);
            if (missingTarget is not null)
            {
                Logger.Error("啟動目標檔案不存在: {Target}", missingTarget);
                _ = UpdateServerStatusInPlaceAsync();
                _notificationSink?.Invoke($"啟動目標檔案不存在：{missingTarget}", true);
                return false;
            }

            var (javaPath, javaError) = await ResolveJavaExecutableAsync(server.MinecraftVersion.Value).ConfigureAwait(true);
            if (javaError is not null)
            {
                Logger.Error("解析 Java 執行環境失敗: {Message}", javaError);
                _notificationSink?.Invoke(javaError, true);
                return false;
            }

            var plan = _launchPlanner!.CreatePlan(server, inspection, javaPath);

            // 啟動前即開啟或帶至前景監控視窗，讓使用者能即時看到啟動記錄
            MonitorServerByName(server.Name.Value, server.Path, server.MinecraftVersion.Value);

            await _serverRuntime.StartAsync(plan).ConfigureAwait(true);
            _ = UpdateServerStatusInPlaceAsync();

            // 啟動後偵測是否於 3 秒內異常結束
            string? earlyExit = await DetectEarlyExitAsync().ConfigureAwait(true);
            if (earlyExit is not null)
            {
                Logger.Error("伺服器啟動後異常結束: {Message}", earlyExit);
                _notificationSink?.Invoke(earlyExit, true);
                _ = UpdateServerStatusInPlaceAsync();
                return false;
            }

            Logger.Information("伺服器已成功啟動: {Name} (版本: {Version})", server.Name.Value, server.MinecraftVersion.Value);
            return true;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "啟動伺服器失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"啟動伺服器失敗：{ex.Message}", true);
            return false;
        }
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
                _ = UpdateServerStatusInPlaceAsync();
                Logger.Information("伺服器已成功傳送停止請求: {Name}", SelectedServer.Name);
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "停止伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"停止伺服器失敗：{ex.Message}", true);
                return;
            }
        }
    }

    [RelayCommand(CanExecute = nameof(CanStartOrMonitorServer))]
    public void MonitorServer()
    {
        if (SelectedServer is null || SelectedServer.HasMissingFiles)
        {
            return;
        }

        MonitorServerByName(SelectedServer.Name, SelectedServer.Path, SelectedServer.Version);
    }

    public void MonitorServerByName(string serverName, string serverPath = "", string mcVersion = "")
    {
        if (_serverRuntime is null)
        {
            return;
        }

        if (_activeMonitorWindow is { IsOpen: true })
        {
            _activeMonitorWindow.BringToFront();
            return;
        }

        var vm = new ServerMonitorViewModel(
            _serverRuntime,
            serverName,
            serverPath,
            mcVersion,
            startRequestHandler: () => StartServerByNameAsync(serverName),
            uiService: _ui);
        _activeMonitorViewModel = vm;
        _activeMonitorWindow = _ui.OpenServerMonitor(vm);
        _activeMonitorWindow.Closed += () =>
        {
            _activeMonitorWindow = null;
            _activeMonitorViewModel?.Dispose();
            _activeMonitorViewModel = null;
        };
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
            var vm = new ServerPropertiesViewModel(store, SelectedServer.Name,
            uiService: _ui);
            if (_ui.ShowServerProperties(vm) == true)
            {
                _notificationSink?.Invoke($"伺服器「{SelectedServer.Name}」屬性設定已更新", false);
            }
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task OpenServerFolder()
    {
        if (SelectedServer is null)
        {
            return;
        }

        string serverFolder = SelectedServer.Path;
        if (!await Task.Run(() => Directory.Exists(serverFolder)).ConfigureAwait(true))
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

        string serverName = SelectedServer.Name;
        string destinationPath;

        if (!string.IsNullOrWhiteSpace(SelectedServer.BackupPath))
        {
            try
            {
                string backupRoot = SelectedServer.BackupPath;
                await Task.Run(() => Directory.CreateDirectory(backupRoot)).ConfigureAwait(true);
            }
            catch (Exception ex)
            {
                _notificationSink?.Invoke($"建立備份目錄失敗：{ex.Message}", true);
                return;
            }

            destinationPath = Path.Combine(SelectedServer.BackupPath, $"backup-{serverName}-{DateTime.Now:yyyyMMdd-HHmmss}.zip");
        }
        else
        {
            string? savePath = _ui.PickSaveFile($"請選擇伺服器「{serverName}」的備份儲存檔案路徑", $"backup-{serverName}-{DateTime.Now:yyyyMMdd-HHmmss}.zip", "ZIP 壓縮檔 (*.zip)|*.zip");
            if (savePath is null)
            {
                return;
            }

            destinationPath = savePath;
        }

        string? boundaryViolation = ValidateBackupDestination(destinationPath);
        if (boundaryViolation is not null)
        {
            Logger.Warning("備份路徑越界遭阻擋: {Path}", destinationPath);
            _notificationSink?.Invoke(boundaryViolation, true);
            return;
        }

        if (_backupService is not null)
        {
            var progressDialog = _ui.ShowServerBackupProgress(serverName);

            try
            {
                var backup = await Task.Run(async () =>
                {
                    return await _backupService.CreateBackupAsync(
                        serverName,
                        destinationPath: destinationPath,
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

                progressDialog.Complete();
                Logger.Information("伺服器「{Name}」備份建立成功: {File}", serverName, backup.FullPath);
                _notificationSink?.Invoke($"已成功建立伺服器「{serverName}」備份：{backup.FileName}", false);
                await RefreshServers();
                return;
            }
            catch (OperationCanceledException)
            {
                progressDialog.Complete();
                Logger.Information("使用者取消了伺服器「{Name}」的備份操作", serverName);
                _notificationSink?.Invoke($"已取消備份「{serverName}」", true);
                return;
            }
            catch (Exception ex)
            {
                progressDialog.Complete();
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
    public async Task RestoreBackup()
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
                isServerRunningCheck: () => isRunning,
            uiService: _ui);
            if (_ui.ShowRestoreBackup(vm) == true)
            {
                string serverName = SelectedServer.Name;
                Logger.Information("伺服器「{Name}」備份已成功還原", serverName);
                await RefreshAndSelectServerAsync(serverName).ConfigureAwait(true);
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

        ServerDeleteDecision decision = _ui.ShowServerDeleteConfirmation(name, backupCount);
        if (decision == ServerDeleteDecision.Cancel)
        {
            return;
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

        if (_ui.ShowServerMemory(vm) == true)
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
                _notificationSink?.Invoke("重新偵測失敗：目錄不包含有效的 Minecraft 伺服器檔案", true);
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

            _ui.ShowNotificationPopup("重新偵測完成", $"已重新偵測伺服器：{config.Name.Value}\nMinecraft 版本：{mv.Value}\n載入器類型：{lk}\n載入器版本：{updated.LoaderVersion}", NotificationLevel.Info);
        }
        catch (Exception ex)
        {
            _notificationSink?.Invoke($"重新偵測失敗：{ex.Message}", true);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task OpenBackupFolder()
    {
        if (SelectedServer is null)
        {
            return;
        }

        string? backupFolder = SelectedServer.BackupPath;
        if (string.IsNullOrWhiteSpace(backupFolder) || !await Task.Run(() => Directory.Exists(backupFolder)).ConfigureAwait(true))
        {
            if (_ui.Confirm(
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

        string? folder = _ui.PickFolder($"選擇伺服器「{SelectedServer.Name}」的外部備份資料夾", !string.IsNullOrWhiteSpace(config.BackupPath) && Directory.Exists(config.BackupPath) ? config.BackupPath : null);
        if (!string.IsNullOrWhiteSpace(folder))
        {
            string selected = folder.Trim();
            string? invalidReason = ValidateBackupDestination(selected);
            if (invalidReason is not null)
            {
                _ui.ShowWarning(invalidReason, "備份路徑無效");
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
    /// 檢查伺服器是否缺失關鍵啟動檔案，並回傳缺失檔案清單。
    /// </summary>
    private static (bool HasMissing, IReadOnlyList<string> MissingFiles) CheckImportantFiles(string serverPath, string? loader = null)
    {
        if (string.IsNullOrWhiteSpace(serverPath) || !Directory.Exists(serverPath))
        {
            return (true, ["伺服器目錄不存在"]);
        }

        try
        {
            var lk = Enum.TryParse<LoaderKind>(loader, ignoreCase: true, out var kind) ? kind : LoaderKind.Unknown;

            switch (lk)
            {
                case LoaderKind.Paper:
                    {
                        bool hasPaper = File.Exists(Path.Combine(serverPath, "paper.jar")) ||
                                        File.Exists(Path.Combine(serverPath, "server.jar")) ||
                                        Directory.EnumerateFiles(serverPath, "paper*.jar", SearchOption.TopDirectoryOnly).Any();
                        return hasPaper ? (false, []) : (true, ["paper.jar"]);
                    }

                case LoaderKind.Fabric:
                    {
                        var missing = new List<string>(2);
                        if (!File.Exists(Path.Combine(serverPath, "fabric-server-launch.jar")))
                        {
                            missing.Add("fabric-server-launch.jar");
                        }
                        if (!File.Exists(Path.Combine(serverPath, "server.jar")))
                        {
                            missing.Add("server.jar");
                        }
                        return missing.Count == 0 ? (false, []) : (true, missing);
                    }

                case LoaderKind.Quilt:
                    {
                        bool hasQuiltLaunch = File.Exists(Path.Combine(serverPath, "quilt-server-launch.jar")) ||
                                              File.Exists(Path.Combine(serverPath, "server", "quilt-server-launch.jar"));
                        bool hasVanillaServer = File.Exists(Path.Combine(serverPath, "server.jar"));

                        if (hasQuiltLaunch || hasVanillaServer)
                        {
                            return (false, []);
                        }

                        return (true, ["quilt-server-launch.jar"]);
                    }

                case LoaderKind.NeoForge:
                    {
                        string neoLib = Path.Combine(serverPath, "libraries", "net", "neoforged", "neoforge");
                        bool hasWinArgs = Directory.Exists(neoLib) && Directory.EnumerateFiles(neoLib, "*args.txt", SearchOption.AllDirectories).Any();
                        bool hasRunScript = File.Exists(Path.Combine(serverPath, "run.bat")) || File.Exists(Path.Combine(serverPath, "run.sh"));

                        if (hasWinArgs || hasRunScript)
                        {
                            return (false, []);
                        }

                        return (true, ["win_args.txt"]);
                    }

                case LoaderKind.Forge:
                    {
                        string forgeLib = Path.Combine(serverPath, "libraries", "net", "minecraftforge", "forge");
                        bool hasForgeArgs = Directory.Exists(forgeLib) && Directory.EnumerateFiles(forgeLib, "*args.txt", SearchOption.AllDirectories).Any();
                        bool hasRunScript = File.Exists(Path.Combine(serverPath, "run.bat")) || File.Exists(Path.Combine(serverPath, "run.sh"));
                        bool hasLegacyForge = Directory.EnumerateFiles(serverPath, "forge*.jar", SearchOption.TopDirectoryOnly).Any();

                        if (hasForgeArgs || hasRunScript || hasLegacyForge)
                        {
                            return (false, []);
                        }

                        return (true, ["win_args.txt"]);
                    }

                default:
                    {
                        bool hasAnyServer = File.Exists(Path.Combine(serverPath, "server.jar")) ||
                                            File.Exists(Path.Combine(serverPath, "run.bat")) ||
                                            Directory.EnumerateFiles(serverPath, "*.jar", SearchOption.TopDirectoryOnly).Any();
                        return hasAnyServer ? (false, []) : (true, ["server.jar"]);
                    }
            }
        }
        catch
        {
            return (true, ["未預期的檔案系統錯誤"]);
        }
    }

    /// <summary>
    /// 驗證啟動 JAR 或腳本是否確實存在，存在則回傳 null，缺失則回傳檔名。
    /// </summary>
    private static string? ResolveMissingLaunchTarget(string serverPath, string launchTarget)
    {
        string target = string.IsNullOrWhiteSpace(launchTarget) ? "server.jar" : launchTarget.Trim();
        if (target.StartsWith('@'))
        {
            target = target[1..].Trim();
        }
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
    /// 啟動後等待 3 秒，若子行程已異常結束則回傳錯誤訊息。
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
            : $"伺服器啟動後立即結束（結束代碼 {exitCode}），請開啟監控主控台檢視詳細輸出以確認原因";
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
            var dirInfo = new DirectoryInfo(directoryPath);
            long bytes = 0L;
            foreach (var fi in dirInfo.EnumerateFiles("*", SearchOption.AllDirectories))
            {
                try
                {
                    bytes += fi.Length;
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Debug("取得檔案大小失敗 ({Path}): {Message}", fi.FullName, ex.Message);
                }
            }

            return Core.Utilities.MemoryUtils.FormatBytes(bytes);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Debug("計算目錄容量失敗 ({Path}): {Message}", directoryPath, ex.Message);
            return "-";
        }
    }
}
