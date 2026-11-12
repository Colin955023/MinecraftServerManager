using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器清單項目展示模型</summary>
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
    public partial long RawSizeBytes { get; set; } = -1;

    [ObservableProperty]
    public partial string BackupStatus { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Path { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string RelativePath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial int MemoryMaxMb { get; set; } = ServerDefaults.DefaultMemoryMaxMb;

    [ObservableProperty]
    public partial int? MemoryMinMb { get; set; }

    [ObservableProperty]
    public partial string? BackupPath { get; set; }

    [ObservableProperty]
    public partial bool HasMissingFiles { get; set; }

    [ObservableProperty]
    public partial string LastModified { get; set; } = "-";

    [ObservableProperty]
    public partial long RawLastModifiedTicks { get; set; } = -1;
}

/// <summary>伺服器管理頁：伺服器清單、選取狀態、執行狀態探測與目錄大小背景計算</summary>
public sealed partial class ServerListViewModel : ViewModelBase, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerListViewModel));

    private readonly IUiService _ui;
    private readonly SettingsManager _settingsManager;
    private readonly IServerManager _serverManager;
    private readonly IServerBackupService _backupService;
    private const string StoppingStatusText = "停止中";

    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly IServerIntegrityService _integrityService;
    private readonly IServerDirectorySizeService _directorySizeService;
    private readonly ILocalFileSystem _fileSystem;
    private readonly Action<string> _navigateCallback;
    private CancellationTokenSource? _sizeCalculationCts;

    [ObservableProperty]
    public partial string DetectPath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial ServerRowItem? SelectedServer { get; set; }

    [ObservableProperty]
    public partial string SelectedServerMemory { get; set; } = "-";

    [ObservableProperty]
    public partial string SelectedServerBackupPath { get; set; } = "-";

    [ObservableProperty]
    public partial bool IsBusy { get; set; }

    [ObservableProperty]
    public partial string BusyStatusText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool HasSelectedServer { get; set; }

    public BulkObservableCollection<ServerRowItem> Servers { get; } = [];

    public bool CanStartOrMonitorServer => HasSelectedServer && SelectedServer is not null && !SelectedServer.HasMissingFiles;

    public bool CanManagePlayers => HasSelectedServer && !IsSelectedServerActive;

    /// <summary>選取伺服器是否為目前執行中的伺服器</summary>
    public bool IsSelectedServerActive =>
        SelectedServer is not null &&
        (_runtimeHost.IsRunning(SelectedServer.Name) ||
         string.Equals(SelectedServer.Status, "執行中", StringComparison.OrdinalIgnoreCase) ||
         string.Equals(SelectedServer.Status, StoppingStatusText, StringComparison.OrdinalIgnoreCase));

    /// <summary>選取伺服器或其詳細資訊變更時觸發（供兄弟子 ViewModel 更新命令可用狀態）</summary>
    public event Action? SelectionStateChanged;

    public ServerListViewModel(
        SettingsManager settingsManager,
        IServerManager serverManager,
        IServerBackupService backupService,
        IServerRuntimeHost runtimeHost,
        ServerStopCoordinator stopCoordinator,
        IServerIntegrityService integrityService,
        IServerDirectorySizeService directorySizeService,
        ILocalFileSystem fileSystem,
        IUiService uiService,
        Action<string> navigateCallback)
    {
        ArgumentNullException.ThrowIfNull(navigateCallback);
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(backupService);
        ArgumentNullException.ThrowIfNull(runtimeHost);
        ArgumentNullException.ThrowIfNull(stopCoordinator);
        ArgumentNullException.ThrowIfNull(integrityService);
        ArgumentNullException.ThrowIfNull(directorySizeService);
        ArgumentNullException.ThrowIfNull(fileSystem);

        _ui = uiService;
        _settingsManager = settingsManager;
        _serverManager = serverManager;
        _backupService = backupService;
        _runtimeHost = runtimeHost;
        _stopCoordinator = stopCoordinator;
        _integrityService = integrityService;
        _directorySizeService = directorySizeService;
        _fileSystem = fileSystem;
        _navigateCallback = navigateCallback;
        DetectPath = ResolveServersDirectory();

        _runtimeHost.ServerStateChanged += OnServerStateChanged;
        _stopCoordinator.StoppingStateChanged += OnServerStateChanged;
    }

    public void Dispose()
    {
        _runtimeHost.ServerStateChanged -= OnServerStateChanged;
        _stopCoordinator.StoppingStateChanged -= OnServerStateChanged;
        CancelSizeCalculation();
        _sizeCalculationCts?.Dispose();
        _sizeCalculationCts = null;
    }

    /// <summary>取得已驗證之伺服器存放根目錄，驗證失敗時改用設定值</summary>
    public string ResolveServersDirectory()
    {
        try
        {
            return _settingsManager.GetValidatedServersRootPath();
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得已驗證之伺服器根目錄失敗，改用設定值");
            return _settingsManager.GetServersRoot();
        }
    }

    partial void OnSelectedServerChanged(ServerRowItem? value) => UpdateSelectedServerDetails(value);

    /// <summary>重新計算選取伺服器之詳細資訊並通知相依命令</summary>
    public void UpdateSelectedServerDetails(ServerRowItem? value)
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
        }
        else
        {
            SelectedServerMemory = "-";
            SelectedServerBackupPath = "-";
        }

        OnPropertyChanged(nameof(CanStartOrMonitorServer));
        OnPropertyChanged(nameof(CanManagePlayers));
        OnPropertyChanged(nameof(IsSelectedServerActive));
        SelectionStateChanged?.Invoke();
    }

    [RelayCommand]
    public void AddServer() => _navigateCallback("create");

    [RelayCommand]
    public async Task DetectServers()
    {
        try
        {
            var report = await _serverManager.ScanAndRegisterAsync();
            await RefreshServers();
            _ui.Notify(
                $"偵測完成：已管理 {report.AlreadyManaged} 個，新增 {report.NewlyAdded} 個，跳過 {report.Skipped} 個",
                NotificationType.Success);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "偵測現有伺服器失敗");
            _ui.Notify($"偵測現有伺服器失敗：{ex.Message}", NotificationType.Error);
        }
    }

    [RelayCommand]
    public async Task RefreshServers()
    {
        IsBusy = true;
        BusyStatusText = "正在載入伺服器清單...";
        try
        {
            DetectPath = ResolveServersDirectory();
            string? prevSelectedName = SelectedServer?.Name;
            var serverEntries = await _serverManager.GetAllServersAsync();
            var running = new HashSet<string>(_runtimeHost.GetRunningServerNames(), StringComparer.OrdinalIgnoreCase);

            IReadOnlyList<ServerRowSnapshot> snapshots = await Task.Run(() =>
                serverEntries.Select(s => BuildServerSnapshot(s, running.Contains(s.Name.Value))).ToList())
                .ConfigureAwait(true);

            ReconcileRows(snapshots);

            if (!string.IsNullOrEmpty(prevSelectedName))
            {
                SelectedServer = FindServer(prevSelectedName) ?? Servers.FirstOrDefault();
            }
            else if (SelectedServer is null || FindServer(SelectedServer.Name) is null)
            {
                SelectedServer = Servers.FirstOrDefault();
            }

            // 確保選取項目之詳細資訊與記憶體顯示即時同步
            UpdateSelectedServerDetails(SelectedServer);
            TriggerBackgroundSizeBackfill();

            Logger.Information("成功重新整理伺服器清單，共 {Count} 個伺服器，路徑: {Path}", Servers.Count, DetectPath);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "載入伺服器清單失敗");
            _ui.Notify($"載入伺服器清單失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            IsBusy = false;
            BusyStatusText = string.Empty;
        }
    }

    /// <summary>重新整理伺服器清單並選取指定名稱之伺服器</summary>
    public async Task RefreshAndSelectServerAsync(string serverName)
    {
        try
        {
            await RefreshServers();
            if (FindServer(serverName) is { } target)
            {
                SelectedServer = target;
            }

            UpdateSelectedServerDetails(SelectedServer);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "重新整理並選取伺服器「{Name}」失敗", serverName);
        }
    }

    /// <summary>自清單移除指定項目並清除選取</summary>
    public void RemoveServer(ServerRowItem row)
    {
        Servers.Remove(row);
        if (ReferenceEquals(SelectedServer, row))
        {
            SelectedServer = null;
        }
    }

    /// <summary>低資源消耗即時更新各伺服器的執行與重要檔案狀態：UI 執行緒僅讀寫集合，檔案檢查於背景執行，不重新掃描目錄大小。</summary>
    public async Task UpdateServerStatusInPlaceAsync()
    {
        try
        {
            var running = new HashSet<string>(_runtimeHost.GetRunningServerNames(), StringComparer.OrdinalIgnoreCase);
            var targets = Servers.Select(s => (Row: s, s.Path, s.Loader, s.Name)).ToList();

            var probes = await Task.Run(() => targets
                .Select(t => ProbeServerStatus(
                    t.Path,
                    LoaderKinds.ParseOrDefault(t.Loader),
                    running.Contains(t.Name),
                    _stopCoordinator.IsStopping(t.Name)))
                .ToList()).ConfigureAwait(true);

            for (int i = 0; i < targets.Count; i++)
            {
                ServerRowItem row = targets[i].Row;
                row.Status = probes[i].Status;
                row.HasMissingFiles = probes[i].HasMissingFiles;
                if (probes[i].LastModified is { } lastModified)
                {
                    row.LastModified = lastModified.ToString("yyyy/MM/dd HH:mm", CultureInfo.InvariantCulture);
                    row.RawLastModifiedTicks = lastModified.Ticks;
                }
            }

            if (SelectedServer is not null)
            {
                UpdateSelectedServerDetails(SelectedServer);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "即時更新伺服器狀態失敗");
        }
    }

    /// <summary>於 UI 執行緒排入伺服器狀態更新（不阻塞呼叫端）</summary>
    public void RequestStatusRefresh() => _ui.PostToUi(() => { _ = RunSafeAsync(UpdateServerStatusInPlaceAsync, "更新伺服器就緒狀態", Logger); });

    private void OnServerStateChanged(string serverName) => RequestStatusRefresh();

    private ServerRowItem? FindServer(string name) =>
        Servers.FirstOrDefault(x => string.Equals(x.Name, name, StringComparison.OrdinalIgnoreCase));

    /// <summary>差分增量對齊（Reconciliation）：保留既有物件與選取狀態，避免捲動跳轉</summary>
    private void ReconcileRows(IReadOnlyList<ServerRowSnapshot> snapshots)
    {
        var existingByName = Servers.ToDictionary(static s => s.Name, StringComparer.OrdinalIgnoreCase);
        var newNames = new HashSet<string>(snapshots.Count, StringComparer.OrdinalIgnoreCase);

        foreach (var snapshot in snapshots)
        {
            string name = snapshot.Config.Name.Value;
            newNames.Add(name);

            if (existingByName.TryGetValue(name, out var row))
            {
                ApplySnapshot(row, snapshot, DetectPath);
            }
            else
            {
                var newRow = new ServerRowItem { Name = name };
                ApplySnapshot(newRow, snapshot, DetectPath);
                Servers.Add(newRow);
            }
        }

        for (int i = Servers.Count - 1; i >= 0; i--)
        {
            if (!newNames.Contains(Servers[i].Name))
            {
                Servers.RemoveAt(i);
            }
        }
    }

    private static void ApplySnapshot(ServerRowItem row, ServerRowSnapshot snapshot, string? baseDirectory)
    {
        ServerConfig s = snapshot.Config;
        row.Version = s.MinecraftVersion.Value;
        row.Loader = s.LoaderType.ToString();
        row.Status = snapshot.Status;
        row.BackupStatus = snapshot.BackupStatus;
        row.LastModified = snapshot.LastModified;
        row.RawLastModifiedTicks = snapshot.RawLastModifiedTicks;
        row.Path = s.Path;
        row.RelativePath = !string.IsNullOrWhiteSpace(baseDirectory) && !string.IsNullOrWhiteSpace(s.Path)
            ? Path.GetRelativePath(baseDirectory, s.Path)
            : s.Path;
        row.MemoryMaxMb = s.MemoryMaxMb;
        row.MemoryMinMb = s.MemoryMinMb;
        row.BackupPath = s.BackupPath;
        row.HasMissingFiles = snapshot.HasMissingFiles;
    }

    private void CancelSizeCalculation()
    {
        try
        {
            _sizeCalculationCts?.Cancel();
        }
        catch (ObjectDisposedException ex)
        {
            Logger.Information("取消目錄大小計算時權杖已釋放: {Message}", ex.Message);
        }
    }

    private void TriggerBackgroundSizeBackfill()
    {
        CancelSizeCalculation();
        _sizeCalculationCts?.Dispose();
        var cts = new CancellationTokenSource();
        _sizeCalculationCts = cts;
        var token = cts.Token;

        var targets = Servers.Select(s => (Row: s, s.Path)).ToList();

        _ = RunSafeAsync(() => Task.Run(async () =>
        {
            try
            {
                // 最多同時計算 2 個伺服器目錄，避免磁碟 I/O 壅塞
                await Parallel.ForEachAsync(targets, new ParallelOptions { MaxDegreeOfParallelism = 2, CancellationToken = token }, async (target, ct) =>
                {
                    try
                    {
                        long bytes = await _directorySizeService.CalculateServerSizeAsync(target.Path, ct).ConfigureAwait(false);
                        string formatted = _directorySizeService.FormatServerSize(bytes);

                        _ui.PostToUi(() =>
                        {
                            if (ct.IsCancellationRequested)
                            {
                                return;
                            }

                            target.Row.RawSizeBytes = bytes;
                            target.Row.Size = formatted;
                            if (ReferenceEquals(SelectedServer, target.Row))
                            {
                                UpdateSelectedServerDetails(SelectedServer);
                            }
                        });
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        Logger.Warning(ex, "非同步計算伺服器目錄大小失敗 ({Path})", target.Path);
                    }
                }).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                Logger.Information("伺服器目錄大小背景計算已取消");
            }
        }, token), "伺服器目錄大小背景計算", Logger);
    }

    private sealed record ServerRowSnapshot(
        ServerConfig Config,
        string BackupStatus,
        string Status,
        string LastModified,
        long RawLastModifiedTicks,
        bool HasMissingFiles);

    private sealed record ServerStatusProbe(string Status, bool HasMissingFiles, DateTime? LastModified);

    private ServerRowSnapshot BuildServerSnapshot(ServerConfig s, bool isThisServerRunning)
    {
        ServerStatusProbe probe = ProbeServerStatus(s.Path, s.LoaderType, isThisServerRunning, _stopCoordinator.IsStopping(s.Name.Value));
        return new ServerRowSnapshot(
            Config: s,
            BackupStatus: FormatBackupStatus(_backupService.GetBackupSummary(s.Name.Value, s.BackupPath)),
            Status: probe.Status,
            LastModified: probe.LastModified?.ToString("yyyy/MM/dd HH:mm", CultureInfo.InvariantCulture) ?? "-",
            RawLastModifiedTicks: probe.LastModified?.Ticks ?? -1,
            HasMissingFiles: probe.HasMissingFiles);
    }

    private ServerStatusProbe ProbeServerStatus(string path, LoaderKind loader, bool isRunning, bool stopping = false)
    {
        if (isRunning)
        {
            return new ServerStatusProbe(stopping ? StoppingStatusText : "執行中", false, GetLastModifiedTime(path));
        }

        var result = _integrityService.CheckImportantFiles(path, loader);
        string status = result.HasMissing ? $"缺少重要檔案：{string.Join("、", result.MissingFiles)}" : "已停止";
        return new ServerStatusProbe(status, result.HasMissing, GetLastModifiedTime(path));
    }

    private DateTime? GetLastModifiedTime(string path)
    {
        try
        {
            return _fileSystem.GetDirectoryLastWriteTime(path);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得目錄最後修改時間失敗: {Path}", path);
            return null;
        }
    }

    /// <summary>將備份摘要格式化為清單顯示文字</summary>
    public static string FormatBackupStatus(ServerBackupSummary summary)
    {
        ArgumentNullException.ThrowIfNull(summary);
        return summary.Status switch
        {
            ServerBackupSummaryStatus.NotConfigured => "未設定外部備份",
            ServerBackupSummaryStatus.DirectoryMissing => "備份資料夾不存在",
            ServerBackupSummaryStatus.NoBackups => "尚無備份",
            ServerBackupSummaryStatus.HasBackups when summary.LatestWriteTime is { } latest =>
                $"{summary.Count} 個備份（{FormatRelativeTime(latest)}）",
            ServerBackupSummaryStatus.HasBackups => $"{summary.Count} 個備份",
            _ => "讀取備份失敗",
        };
    }

    /// <summary>將時間格式化為相對時間描述</summary>
    public static string FormatRelativeTime(DateTime timestamp)
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

    private static string FormatMemoryDisplay(int? minMb, int maxMb) =>
        minMb is { } min && min > 0
            ? $"{min} MB ~ {maxMb} MB"
            : $"{maxMb} MB";
}
