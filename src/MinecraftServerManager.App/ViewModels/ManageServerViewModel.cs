using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器列表項目展示模型
/// </summary>
public sealed partial class ServerRowItem : ObservableObject
{
    [ObservableProperty]
    public partial string Name { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Version { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Loader { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Status { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Size { get; set; } = "-";

    [ObservableProperty]
    public partial string BackupStatus { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Path { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string RelativePath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial int MemoryMaxMb { get; set; } = 2048;

    [ObservableProperty]
    public partial int? MemoryMinMb { get; set; }

    [ObservableProperty]
    public partial string? BackupPath { get; set; }

    [ObservableProperty]
    public partial bool HasMissingFiles { get; set; }

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
    private readonly IServerPlayerConfigStore _playerConfigStore;
    private readonly IJavaRuntimeDetector? _javaDetector;
    private readonly IMinecraftJavaRequirementService? _javaRequirementService;
    private readonly IExternalLauncher? _launcher;
    private readonly IServerDirectorySizeService _directorySizeService;
    private readonly IServerIntegrityService _integrityService;
    private readonly Action<string>? _navigateCallback;
    private readonly Action<string, bool>? _notificationSink;
    private IMonitorWindow? _activeMonitorWindow;
    private ServerMonitorViewModel? _activeMonitorViewModel;
    private CancellationTokenSource? _sizeCalculationCts;

    [ObservableProperty]
    public partial string DetectPath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial ServerRowItem? SelectedServer { get; set; }

    [ObservableProperty]
    public partial string SelectedServerInfo { get; set; } = "選擇一個伺服器以檢視詳細資訊";

    [ObservableProperty]
    public partial string SelectedServerMemory { get; set; } = "-";

    [ObservableProperty]
    public partial string SelectedServerBackupPath { get; set; } = "-";

    [ObservableProperty]
    public partial bool IsBusy { get; set; }

    [ObservableProperty]
    public partial string BusyStatusText { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(MonitorServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(ConfigureServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(ManagePlayersCommand))]
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
    public bool CanManagePlayers => HasSelectedServer && !IsSelectedServerActive;
    public bool IsSelectedServerRunning => IsSelectedServerActive;

    private bool IsSelectedServerActive =>
        SelectedServer is not null &&
        ((_serverRuntime is not null && _serverRuntime.IsRunning && string.Equals(_serverRuntime.ActiveServerName, SelectedServer.Name, StringComparison.OrdinalIgnoreCase)) ||
         string.Equals(SelectedServer.Status, "執行中", StringComparison.OrdinalIgnoreCase));

    public ManageServerViewModel(
        SettingsManager settingsManager,
        IServerManager serverManager,
        IServerBackupService backupService,
        IServerRuntime serverRuntime,
        IServerInspector serverInspector,
        IServerLaunchPlanner launchPlanner,
        IServerPropertiesStore propertiesStore,
        IServerPlayerConfigStore playerConfigStore,
        IServerDirectorySizeService directorySizeService,
        IServerIntegrityService integrityService,
        Action<string>? navigateCallback = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null,
        IJavaRuntimeDetector? javaDetector = null,
        IMinecraftJavaRequirementService? javaRequirementService = null,
        IUiService? uiService = null)
        : base("manage", "管理現有伺服器", "檢視已安裝伺服器清單，執行啟動、停止、設定與備份維護")
    {
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(backupService);
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(serverInspector);
        ArgumentNullException.ThrowIfNull(launchPlanner);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentNullException.ThrowIfNull(playerConfigStore);
        ArgumentNullException.ThrowIfNull(directorySizeService);
        ArgumentNullException.ThrowIfNull(integrityService);

        _ui = uiService ?? NoOpUiService.Instance;
        _settingsManager = settingsManager;
        _serverManager = serverManager;
        _backupService = backupService;
        _serverRuntime = serverRuntime;
        _serverInspector = serverInspector;
        _launchPlanner = launchPlanner;
        _propertiesStore = propertiesStore;
        _playerConfigStore = playerConfigStore;
        _directorySizeService = directorySizeService;
        _integrityService = integrityService;
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

        _sizeCalculationCts?.Cancel();
        _sizeCalculationCts?.Dispose();
        _sizeCalculationCts = null;
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

    private static string FormatMemoryDisplay(int? minMb, int maxMb)
    {
        return minMb is { } min && min > 0
            ? $"{min} MB ~ {maxMb} MB"
            : $"{maxMb} MB";
    }

    private void UpdateSelectedServerDetails(ServerRowItem? value)
    {
        HasSelectedServer = value is not null;
        if (value is not null)
        {
            string backupInfo = !string.IsNullOrWhiteSpace(value.BackupPath)
                ? value.BackupPath
                : "未設定外部備份資料夾";

            string memoryDisplay = FormatMemoryDisplay(value.MemoryMinMb, value.MemoryMaxMb);
            SelectedServerMemory = memoryDisplay;
            SelectedServerBackupPath = backupInfo;

            SelectedServerInfo = $"伺服器名稱：{value.Name}\n" +
                                 $"Minecraft 版本：{value.Version}\n" +
                                 $"載入器類型：{value.Loader}\n" +
                                 $"目前狀態：{value.Status}\n" +
                                 $"目錄容量：{value.Size}\n" +
                                 $"備份狀況：{value.BackupStatus}\n" +
                                 $"外部備份路徑：{backupInfo}\n" +
                                 $"記憶體配置：{memoryDisplay}\n" +
                                 $"實體路徑：{value.Path}";
        }
        else
        {
            SelectedServerMemory = "-";
            SelectedServerBackupPath = "-";
            SelectedServerInfo = "選擇一個伺服器以檢視詳細資訊";
        }

        OnPropertyChanged(nameof(CanStartOrMonitorServer));
        OnPropertyChanged(nameof(CanManagePlayers));
        OnPropertyChanged(nameof(IsSelectedServerRunning));
    }

    partial void OnSelectedServerChanged(ServerRowItem? value)
    {
        UpdateSelectedServerDetails(value);
    }

    [RelayCommand]
    public async Task DetectServers()
    {
        if (_serverManager is null)
        {
            _notificationSink?.Invoke("伺服器管理員尚未就緒", true);
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
    private void RequestStatusRefresh() => _ui.PostToUi(() => { _ = RunSafeAsync(UpdateServerStatusInPlaceAsync, "更新伺服器就緒狀態", Logger); });

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

                    IReadOnlyList<ServerRowSnapshot> snapshots = await Task.Run(() =>
                        serverEntries.Select(s => BuildServerSnapshot(s, runtimeRunning, activeName)).ToList())
                        .ConfigureAwait(true);

                    // 差分增量對齊（Reconciliation）：保留既有物件與選取狀態，杜絕捲動跳轉
                    var existingByName = Servers.ToDictionary(static s => s.Name, StringComparer.OrdinalIgnoreCase);
                    var newNames = new HashSet<string>(snapshots.Count, StringComparer.OrdinalIgnoreCase);

                    foreach (var snapshot in snapshots)
                    {
                        string name = snapshot.Config.Name.Value;
                        newNames.Add(name);

                        if (existingByName.TryGetValue(name, out var existingRow))
                        {
                            existingRow.Version = snapshot.Config.MinecraftVersion.Value;
                            existingRow.Loader = snapshot.Config.LoaderType.ToString();
                            existingRow.Status = snapshot.Status;
                            existingRow.BackupStatus = snapshot.BackupStatus;
                            existingRow.LastModified = snapshot.LastModified;
                            existingRow.Path = snapshot.Config.Path;
                            existingRow.RelativePath = !string.IsNullOrWhiteSpace(DetectPath) && !string.IsNullOrWhiteSpace(snapshot.Config.Path)
                                ? Path.GetRelativePath(DetectPath, snapshot.Config.Path)
                                : snapshot.Config.Path;
                            existingRow.MemoryMaxMb = snapshot.Config.MemoryMaxMb;
                            existingRow.MemoryMinMb = snapshot.Config.MemoryMinMb;
                            existingRow.BackupPath = snapshot.Config.BackupPath;
                            existingRow.HasMissingFiles = snapshot.HasMissingFiles;
                        }
                        else
                        {
                            Servers.Add(ToRowItem(snapshot, DetectPath));
                        }
                    }

                    for (int i = Servers.Count - 1; i >= 0; i--)
                    {
                        if (!newNames.Contains(Servers[i].Name))
                        {
                            Servers.RemoveAt(i);
                        }
                    }

                    if (!string.IsNullOrEmpty(prevSelectedName))
                    {
                        SelectedServer = Servers.FirstOrDefault(x => string.Equals(x.Name, prevSelectedName, StringComparison.OrdinalIgnoreCase)) ?? Servers.FirstOrDefault();
                    }
                    else if (SelectedServer is null || !newNames.Contains(SelectedServer.Name))
                    {
                        SelectedServer = Servers.FirstOrDefault();
                    }

                    // 確保選取項目之詳細資訊與記憶體顯示即時同步
                    UpdateSelectedServerDetails(SelectedServer);

                    // 啟動背景容量非同步回填
                    TriggerBackgroundSizeBackfill();

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

    private void TriggerBackgroundSizeBackfill()
    {
        _sizeCalculationCts?.Cancel();
        _sizeCalculationCts?.Dispose();
        var cts = new CancellationTokenSource();
        _sizeCalculationCts = cts;
        var token = cts.Token;

        var targets = Servers.Select(s => (Row: s, s.Path)).ToList();

        _ = Task.Run(async () =>
        {
            using var semaphore = new SemaphoreSlim(2, 2);
            var tasks = targets.Select(async target =>
            {
                await semaphore.WaitAsync(token).ConfigureAwait(false);
                try
                {
                    token.ThrowIfCancellationRequested();
                    long bytes = await _directorySizeService.CalculateServerSizeAsync(target.Path, token).ConfigureAwait(false);
                    string formatted = _directorySizeService.FormatServerSize(bytes);

                    _ui.PostToUi(() =>
                    {
                        if (!token.IsCancellationRequested)
                        {
                            target.Row.Size = formatted;
                        }
                    });
                }
                catch (OperationCanceledException)
                {
                    // 正常切換伺服器或重新整理時取消背景容量計算，不寫入日誌以維持記錄檔整潔
                }
                catch (Exception ex)
                {
                    Logger.Warning("非同步計算伺服器容量失敗 ({Path}): {Message}", target.Path, ex.Message);
                }
                finally
                {
                    semaphore.Release();
                }
            });

            await Task.WhenAll(tasks).ConfigureAwait(false);
        }, token);
    }

    private sealed record ServerRowSnapshot(
        ServerConfig Config,
        string Size,
        string BackupStatus,
        string Status,
        string LastModified,
        bool HasMissingFiles);

    private sealed record ServerStatusProbe(string Status, bool HasMissingFiles, string? LastModified);

    private ServerRowSnapshot BuildServerSnapshot(ServerConfig s, bool runtimeRunning, string? activeName)
    {
        bool isThisServerRunning = runtimeRunning && string.Equals(activeName, s.Name.Value, StringComparison.OrdinalIgnoreCase);
        ServerStatusProbe probe = ProbeServerStatus(s.Path, s.LoaderType, isThisServerRunning);
        return new ServerRowSnapshot(
            Config: s,
            Size: "-",
            BackupStatus: BuildBackupStatus(s),
            Status: probe.Status,
            LastModified: probe.LastModified ?? "-",
            HasMissingFiles: probe.HasMissingFiles);
    }

    private static ServerRowItem ToRowItem(ServerRowSnapshot snapshot, string? baseDirectory = null)
    {
        ServerConfig s = snapshot.Config;
        string relPath = !string.IsNullOrWhiteSpace(baseDirectory) && !string.IsNullOrWhiteSpace(s.Path)
            ? Path.GetRelativePath(baseDirectory, s.Path)
            : s.Path;

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
            RelativePath = relPath,
            MemoryMaxMb = s.MemoryMaxMb,
            MemoryMinMb = s.MemoryMinMb,
            BackupPath = s.BackupPath,
            HasMissingFiles = snapshot.HasMissingFiles,
        };
    }

    private ServerStatusProbe ProbeServerStatus(string path, LoaderKind loader, bool isRunning)
    {
        if (isRunning)
        {
            return new ServerStatusProbe("執行中", false, GetLastModifiedText(path));
        }

        var result = _integrityService.CheckImportantFiles(path, loader);
        string status = result.HasMissing ? $"缺少重要檔案：{string.Join("、", result.MissingFiles)}" : "已停止";
        return new ServerStatusProbe(status, result.HasMissing, GetLastModifiedText(path));
    }

    private static string BuildBackupStatus(ServerConfig s)
    {
        if (string.IsNullOrWhiteSpace(s.BackupPath))
        {
            return "未設定外部備份";
        }

        if (!SafeFileSystem.DirectoryExists(s.BackupPath))
        {
            return "備份資料夾不存在";
        }

        try
        {
            string serverName = s.Name.Value;
            string prefix = $"backup-{serverName}-";
            string altPrefix = $"{serverName}-";
            string exact1 = $"backup-{serverName}.zip";
            string exact2 = $"{serverName}.zip";

            var archives = SafeFileSystem.EnumerateFiles(s.BackupPath, "*.zip")
                .Where(f =>
                {
                    string fn = Path.GetFileName(f);
                    return fn.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
                           fn.StartsWith(altPrefix, StringComparison.OrdinalIgnoreCase) ||
                           string.Equals(fn, exact1, StringComparison.OrdinalIgnoreCase) ||
                           string.Equals(fn, exact2, StringComparison.OrdinalIgnoreCase);
                })
                .ToList();

            if (archives.Count > 0)
            {
                DateTime latest = archives.Max(SafeFileSystem.GetFileLastWriteTime);
                return $"{archives.Count} 個備份（{FormatRelativeTime(latest)}）";
            }

            return "尚無備份";
        }
        catch (Exception ex)
        {
            Logger.Warning("讀取備份清單失敗 ({Path}): {Message}", s.BackupPath, ex.Message);
            return "讀取備份失敗";
        }
    }

    private static string? GetLastModifiedText(string path)
    {
        try
        {
            return SafeFileSystem.DirectoryExists(path)
                ? SafeFileSystem.GetDirectoryLastWriteTime(path).ToString("yyyy/MM/dd HH:mm", CultureInfo.InvariantCulture)
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
        try
        {
            bool runtimeRunning = _serverRuntime?.IsRunning == true;
            string? activeName = _serverRuntime?.ActiveServerName;
            var targets = Servers.Select(s => (Row: s, s.Path, s.Loader, s.Name)).ToList();

            var probes = await Task.Run(() => targets
                .Select(t =>
                {
                    var lk = Enum.TryParse<LoaderKind>(t.Loader, ignoreCase: true, out var parsedLk) ? parsedLk : LoaderKind.Unknown;
                    return ProbeServerStatus(
                        t.Path,
                        lk,
                        runtimeRunning && string.Equals(activeName, t.Name, StringComparison.OrdinalIgnoreCase));
                })
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
        catch (Exception ex)
        {
            Logger.Warning("即時更新伺服器狀態失敗: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 重新整理伺服器清單並選取指定名稱之伺服器
    /// </summary>
    public async Task RefreshAndSelectServerAsync(string serverName)
    {
        try
        {
            await RefreshServers();
            var target = Servers.FirstOrDefault(s => string.Equals(s.Name, serverName, StringComparison.OrdinalIgnoreCase));
            if (target is not null)
            {
                SelectedServer = target;
            }
            UpdateSelectedServerDetails(SelectedServer);
        }
        catch (Exception ex)
        {
            Logger.Warning("重新整理並選取伺服器「{Name}」失敗: {Message}", serverName, ex.Message);
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
                _ = RunSafeAsync(UpdateServerStatusInPlaceAsync, "更新伺服器就緒狀態", Logger);
                _notificationSink?.Invoke($"啟動目標檔案不存在：{missingTarget}", true);
                _ui.ShowError($"啟動目標檔案不存在：\n{missingTarget}", "啟動伺服器失敗");
                return false;
            }

            var (javaPath, javaError) = await ResolveJavaExecutableAsync(server.MinecraftVersion.Value, server.LoaderType).ConfigureAwait(true);
            if (javaError is not null)
            {
                Logger.Error("解析 Java 執行環境失敗: {Message}", javaError);
                _notificationSink?.Invoke(javaError, true);
                _ui.ShowError($"解析 Java 執行環境失敗：\n{javaError}", "啟動伺服器失敗");
                return false;
            }

            var plan = _launchPlanner!.CreatePlan(server, inspection, javaPath);

            MonitorServerByName(server.Name.Value, server.Path, server.MinecraftVersion.Value);

            await _serverRuntime.StartAsync(plan).ConfigureAwait(true);
            _ = RunSafeAsync(UpdateServerStatusInPlaceAsync, "更新伺服器就緒狀態", Logger);

            string? earlyExit = await DetectEarlyExitAsync().ConfigureAwait(true);
            if (earlyExit is not null)
            {
                Logger.Error("伺服器啟動後異常結束: {Message}", earlyExit);
                _notificationSink?.Invoke(earlyExit, true);
                _ui.ShowError($"伺服器啟動後異常結束：\n{earlyExit}", "伺服器異常結束");
                _ = RunSafeAsync(UpdateServerStatusInPlaceAsync, "更新伺服器就緒狀態", Logger);
                return false;
            }

            Logger.Information("伺服器已成功啟動: {Name} (版本: {Version})", server.Name.Value, server.MinecraftVersion.Value);
            return true;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "啟動伺服器失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"啟動伺服器失敗：{ex.Message}", true);
            _ui.ShowError($"啟動伺服器失敗：\n{ex.Message}", "啟動伺服器失敗");
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
                _ = RunSafeAsync(UpdateServerStatusInPlaceAsync, "更新伺服器就緒狀態", Logger);
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

        var store = _propertiesStore;
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
    public void ManagePlayers()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (IsSelectedServerActive)
        {
            _notificationSink?.Invoke("伺服器正在運行中，請先停止伺服器後再管理玩家設定", true);
            return;
        }

        var vm = new PlayerManagementViewModel(
            serverName: SelectedServer.Name,
            serverPath: SelectedServer.Path,
            configStore: _playerConfigStore,
            ui: _ui);

        if (_ui.ShowPlayerManagement(vm) == true)
        {
            _notificationSink?.Invoke($"伺服器「{SelectedServer.Name}」名單設定已更新", false);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task OpenServerFolder()
    {
        if (SelectedServer is null)
        {
            return Task.CompletedTask;
        }

        string serverFolder = SelectedServer.Path;
        if (!SafeFileSystem.DirectoryExists(serverFolder))
        {
            _notificationSink?.Invoke($"資料夾不存在：{SelectedServer.Path}", true);
            return Task.CompletedTask;
        }

        if (_launcher is not null && !_launcher.OpenFolder(SelectedServer.Path, isTrusted: true))
        {
            _notificationSink?.Invoke($"無法開啟資料夾：{SelectedServer.Path}", true);
        }

        return Task.CompletedTask;
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task BackupServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        string serverName = SelectedServer.Name;

        if (string.IsNullOrWhiteSpace(SelectedServer.BackupPath))
        {
            _ui.ShowToast("伺服器尚未設定外部備份資料夾，請先設定儲存位置", "請設定備份路徑", ToastType.Info);
            await EditBackupPath();
            if (string.IsNullOrWhiteSpace(SelectedServer.BackupPath))
            {
                return;
            }
        }

        string destinationDir = SelectedServer.BackupPath;
        string? boundaryViolation = ValidateBackupDestination(destinationDir);
        if (boundaryViolation is not null)
        {
            _ui.ShowToast(boundaryViolation, "備份路徑無效，請重新設定", ToastType.Warning);
            await EditBackupPath();
            if (string.IsNullOrWhiteSpace(SelectedServer.BackupPath) || ValidateBackupDestination(SelectedServer.BackupPath) is not null)
            {
                return;
            }
            destinationDir = SelectedServer.BackupPath;
        }

        try
        {
            SafeFileSystem.CreateDirectory(destinationDir);
        }
        catch (Exception ex)
        {
            _notificationSink?.Invoke($"建立備份目錄失敗：{ex.Message}", true);
            return;
        }

        string destinationPath = Path.Combine(destinationDir, $"backup-{serverName}-{DateTime.Now:yyyyMMdd-HHmmss}.zip");

        if (_backupService is not null)
        {
            var progressDialog = _ui.ShowServerBackupProgress(serverName);

            try
            {
                var backup = await _backupService.CreateBackupAsync(
                    serverName,
                    destinationPath: destinationPath,
                    progress: progressDialog.Progress).ConfigureAwait(true);

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
    /// 備份目的地邊界檢查：禁止位於伺服器存放目錄 (servers/) 或其子目錄內。
    /// </summary>
    /// <returns>合法時回傳 null，違規時回傳阻擋訊息。</returns>
    private string? ValidateBackupDestination(string destinationPath)
    {
        string serversRoot = ResolveServersDirectory();
        if (string.IsNullOrWhiteSpace(serversRoot))
        {
            return null;
        }

        try
        {
            string targetDir = SafeFileSystem.FileExists(destinationPath) || destinationPath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase)
                ? (Path.GetDirectoryName(destinationPath) ?? destinationPath)
                : destinationPath;

            string normalizedTarget = Path.GetFullPath(targetDir);
            string normalizedServersRoot = Path.GetFullPath(serversRoot);

            if (SafeFileSystem.IsPathWithin(normalizedServersRoot, normalizedTarget, strict: false))
            {
                return "備份路徑不得位於伺服器存放目錄 (servers/) 或其子目錄內，請重新選擇其他外部資料夾。";
            }

            return null;
        }
        catch (Exception ex)
        {
            return $"路徑解析失敗：{ex.Message}";
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
        string? backupPath = SelectedServer.BackupPath;
        var currentServer = SelectedServer;

        int backupCount = 0;
        IReadOnlyList<ServerBackupInfo>? backupsToDelete = null;
        if (_backupService is not null && !string.IsNullOrWhiteSpace(backupPath))
        {
            try
            {
                var backups = await _backupService.ListBackupsAsync(name, backupPath);
                backupCount = backups.Count;
                backupsToDelete = backups;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "取得伺服器「{Name}」關聯備份清單失敗", name);
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
                if (decision == ServerDeleteDecision.DeleteServerAndBackups && _backupService is not null && backupsToDelete is { Count: > 0 } && !string.IsNullOrWhiteSpace(backupPath))
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
        }, uiService: _ui);

        if (_ui.ShowServerMemory(vm) == true)
        {
            _notificationSink?.Invoke($"已更新伺服器「{SelectedServer.Name}」記憶體設定", false);
            await RefreshAndSelectServerAsync(SelectedServer.Name);
            UpdateSelectedServerDetails(SelectedServer);
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

            _ui.ShowToast($"已重新偵測伺服器：{config.Name.Value}\nMinecraft 版本：{mv.Value}\n載入器類型：{lk}\n載入器版本：{updated.LoaderVersion}", "重新偵測完成", ToastType.Info);
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
        if (string.IsNullOrWhiteSpace(backupFolder) || !SafeFileSystem.DirectoryExists(backupFolder))
        {
            if (_ui.Confirm(
                $"伺服器「{SelectedServer.Name}」尚未設定自訂備份路徑。\n\n是否要立即設定外部備份資料夾？",
                "尚未設定備份資料夾"))
            {
                await EditBackupPath();
            }
            return;
        }

        if (_launcher is not null && !_launcher.OpenFolder(backupFolder, isTrusted: true))
        {
            _notificationSink?.Invoke($"無法開啟備份資料夾：{backupFolder}", true);
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

        while (true)
        {
            string? folder = _ui.PickFolder($"選擇伺服器「{SelectedServer.Name}」的外部備份資料夾", !string.IsNullOrWhiteSpace(config.BackupPath) && SafeFileSystem.DirectoryExists(config.BackupPath) ? config.BackupPath : null);
            if (string.IsNullOrWhiteSpace(folder))
            {
                return;
            }

            string selected = folder.Trim();
            string? invalidReason = ValidateBackupDestination(selected);
            if (invalidReason is not null)
            {
                _ui.ShowToast(invalidReason, "備份路徑無效，請重新選擇", ToastType.Warning);
                continue;
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
            break;
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
            return SafeFileSystem.FileExists(fullPath) ? null : target;
        }
        catch
        {
            return target;
        }
    }

    /// <summary>
    /// 依據 Minecraft 版本與載入器精準解析所需的 Java 實體執行檔路徑。
    /// </summary>
    /// <returns>成功時回傳 (路徑, null)；失敗時回傳 (null, 錯誤訊息)。</returns>
    private async Task<(string? JavaPath, string? Error)> ResolveJavaExecutableAsync(string minecraftVersion, LoaderKind loader = LoaderKind.Unknown)
    {
        if (_javaDetector is null || _javaRequirementService is null)
        {
            return (null, null);
        }

        int requiredMajor;
        try
        {
            requiredMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion, loader).ConfigureAwait(true);
        }
        catch (Exception exception)
        {
            Logger.Warning("查詢 Minecraft {Version} 所需 Java 版本失敗（{Message}），回退使用系統預設 java", minecraftVersion, exception.Message);
            return ("java", null);
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
}
