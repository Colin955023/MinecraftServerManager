using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器清單項目展示模型</summary>
public sealed partial class ServerRowItem : ObservableObject
{
    public string Name { get; init; } = string.Empty;

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

    /// <summary>行程執行中（含停止中）</summary>
    [ObservableProperty]
    public partial bool IsRunning { get; set; }

    /// <summary>正在執行平順停止流程</summary>
    [ObservableProperty]
    public partial bool IsStopping { get; set; }

    /// <summary>狀態探測序號，用於過濾慢速過期探測結果</summary>
    public long StatusProbeSequence { get; set; }
}

/// <summary>伺服器管理頁：伺服器清單、選取狀態、執行狀態偵測與目錄大小背景計算</summary>
public sealed partial class ServerListViewModel : ViewModelBase, IDisposable
{
    private const string StoppingStatusText = "停止中";
    private const string RunningStatusText = "執行中";
    private const int MaxConcurrentServerSnapshots = 4;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerListViewModel));

    private readonly IUiService _ui;
    private readonly ISettingsManager _settingsManager;
    private readonly IServerManager _serverManager;
    private readonly IServerBackupService _backupService;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly IServerIntegrityService _integrityService;
    private readonly IServerDirectorySizeService _directorySizeService;
    private readonly ILocalFileSystem _fileSystem;
    private readonly Action<string> _navigateCallback;
    private readonly SerialCancellation _sizeCalculation = new();
    private readonly SerialCancellation _refresh = new();
    private readonly List<IRelayCommand> _dependentCommands = [];
    private long _statusProbeSequence;

    public ServerListViewModel(
        ISettingsManager settingsManager,
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
        ArgumentNullException.ThrowIfNull(uiService);

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
        // 建構時僅取記憶體設定值，已驗證路徑由首次重新整理於背景執行緒解析
        DetectPath = _settingsManager.GetServersRoot();

        _runtimeHost.ServerStateChanged += OnServerStateChanged;
        _stopCoordinator.StoppingStateChanged += OnServerStateChanged;
    }

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
        (SelectedServer.IsRunning || SelectedServer.IsStopping || _runtimeHost.IsRunning(SelectedServer.Name));

    public void Dispose()
    {
        _runtimeHost.ServerStateChanged -= OnServerStateChanged;
        _stopCoordinator.StoppingStateChanged -= OnServerStateChanged;
        _sizeCalculation.Dispose();
        _refresh.Dispose();
    }

    /// <summary>於背景執行緒取得已驗證之伺服器存放根目錄，驗證失敗時改用設定值</summary>
    public Task<string> ResolveServersDirectoryAsync(CancellationToken cancellationToken = default) =>
        Task.Run(ResolveServersDirectory, cancellationToken);

    private string ResolveServersDirectory()
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

            string memoryDisplay = ServerStatusFormatter.FormatMemoryDisplay(value.MemoryMinMb, value.MemoryMaxMb);
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
        foreach (IRelayCommand command in _dependentCommands)
        {
            command.NotifyCanExecuteChanged();
        }
    }

    /// <summary>登記選取狀態變更時須重新評估可否執行的命令</summary>
    public void RegisterDependentCommands(params IRelayCommand[] commands) => _dependentCommands.AddRange(commands);

    [RelayCommand]
    public void AddServer() => _navigateCallback(PageKeys.Create);

    [RelayCommand]
    public async Task DetectServersAsync()
    {
        try
        {
            var report = await _serverManager.ScanAndRegisterAsync();
            await RefreshServersAsync();
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
    public Task RefreshServersAsync() => RefreshCoreAsync(preferredSelection: null);

    /// <summary>重新整理伺服器清單並選取指定名稱之伺服器</summary>
    public Task RefreshAndSelectServerAsync(string serverName) => RefreshCoreAsync(serverName);

    /// <summary>重新載入清單；較新的重新整理會取消較舊者，避免舊結果覆寫新結果</summary>
    private async Task RefreshCoreAsync(string? preferredSelection)
    {
        CancellationToken token = _refresh.Next();
        IsBusy = true;
        BusyStatusText = "正在載入伺服器清單...";
        try
        {
            DetectPath = await ResolveServersDirectoryAsync(token);
            var serverEntries = await _serverManager.GetAllServersAsync(token);
            var running = new HashSet<string>(_runtimeHost.GetRunningServerNames(), StringComparer.OrdinalIgnoreCase);

            var snapshots = new ServerRowSnapshot[serverEntries.Count];
            await Parallel.ForEachAsync(
                Enumerable.Range(0, serverEntries.Count),
                new ParallelOptions { MaxDegreeOfParallelism = MaxConcurrentServerSnapshots, CancellationToken = token },
                async (index, cancellationToken) =>
                {
                    ServerConfig server = serverEntries[index];
                    snapshots[index] = await BuildServerSnapshotAsync(
                        server,
                        running.Contains(server.Name.Value),
                        cancellationToken).ConfigureAwait(false);
                }).ConfigureAwait(true);
            token.ThrowIfCancellationRequested();

            string? selectName = preferredSelection ?? SelectedServer?.Name;
            ReconcileRows(snapshots);

            var target = (selectName is null ? null : FindServer(selectName)) ?? Servers.FirstOrDefault();
            if (ReferenceEquals(SelectedServer, target))
            {
                // 同一物件不會觸發變更通知，手動同步詳細資訊
                UpdateSelectedServerDetails(target);
            }
            else
            {
                SelectedServer = target;
            }

            TriggerBackgroundSizeBackfill();
            Logger.Information("成功重新整理伺服器清單，共 {Count} 個伺服器，路徑：{Path}", Servers.Count, DetectPath);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("伺服器清單重新整理已被較新的要求取代");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "載入伺服器清單失敗");
            _ui.Notify($"載入伺服器清單失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            if (!token.IsCancellationRequested)
            {
                IsBusy = false;
                BusyStatusText = string.Empty;
            }
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

    /// <summary>更新伺服器的執行與檔案狀態（<paramref name="serverName"/> 為 null 時更新全部），不重新計算目錄大小</summary>
    public async Task UpdateServerStatusInPlaceAsync(string? serverName = null)
    {
        long probeSequence = Interlocked.Increment(ref _statusProbeSequence);
        try
        {
            var running = new HashSet<string>(_runtimeHost.GetRunningServerNames(), StringComparer.OrdinalIgnoreCase);
            var targets = Servers
                .Where(s => serverName is null || string.Equals(s.Name, serverName, StringComparison.OrdinalIgnoreCase))
                .Select(s => (Row: s, s.Path, s.Loader, s.Name))
                .ToList();

            var probes = await Task.WhenAll(targets
                .Select(t => ProbeServerStatusAsync(
                    t.Path,
                    LoaderKinds.ParseOrDefault(t.Loader),
                    running.Contains(t.Name),
                    _stopCoordinator.IsStopping(t.Name))));

            for (int i = 0; i < targets.Count; i++)
            {
                ServerRowItem row = targets[i].Row;
                if (probeSequence < row.StatusProbeSequence)
                {
                    continue;
                }

                row.StatusProbeSequence = probeSequence;
                row.Status = probes[i].Status;
                row.IsRunning = probes[i].IsRunning;
                row.IsStopping = probes[i].IsStopping;
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

    /// <summary>若有選取伺服器則執行指定非同步動作，並自動攔截例外通知使用者</summary>
    public async Task RunForSelectedServerAsync(
        Func<ServerRowItem, Task> action,
        string? failureTitle = null,
        ComponentLogger? logger = null)
    {
        ArgumentNullException.ThrowIfNull(action);
        if (SelectedServer is not { } selected)
        {
            return;
        }

        try
        {
            await action(selected);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger?.Error(ex, failureTitle ?? "執行伺服器操作失敗");
            _ui.Notify($"{(failureTitle is null ? "操作失敗" : failureTitle)}：{ex.Message}", NotificationType.Error);
        }
    }

    /// <summary>更新已選取伺服器的設定檔，更新成功後自動重新整理並選取</summary>
    public async Task<bool> UpdateSelectedServerConfigAsync(
        Func<ServerConfig, ServerConfig> mutator,
        string? successMessage = null,
        string failureTitle = "更新伺服器設定失敗",
        ComponentLogger? logger = null)
    {
        ArgumentNullException.ThrowIfNull(mutator);
        if (SelectedServer is not { } selected)
        {
            return false;
        }

        try
        {
            if (await _ui.GetServerOrWarnAsync(_serverManager, selected.Name) is not { } config)
            {
                return false;
            }

            var updated = mutator(config);
            var result = await _serverManager.UpdateServerAsync(updated);
            if (result.Success)
            {
                if (!string.IsNullOrWhiteSpace(successMessage))
                {
                    _ui.Notify(successMessage, NotificationType.Success);
                }

                await RefreshAndSelectServerAsync(updated.Name.Value);
                return true;
            }

            logger?.Warning("{Title}：{Message}", failureTitle, result.Message);
            _ui.Notify($"{failureTitle}：{result.Message}", NotificationType.Error);
            return false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger?.Error(ex, failureTitle);
            _ui.Notify($"{failureTitle}：{ex.Message}", NotificationType.Error);
            return false;
        }
    }

    /// <summary>於 UI 執行緒排入伺服器狀態更新（不阻塞呼叫端）；指定名稱時僅更新該列</summary>
    public void RequestStatusRefresh(string? serverName = null) =>
        _ui.PostToUi(() => { _ = RunSafeAsync(() => UpdateServerStatusInPlaceAsync(serverName), "更新伺服器就緒狀態", Logger); });

    private void OnServerStateChanged(string serverName) => RequestStatusRefresh(serverName);

    private ServerRowItem? FindServer(string name) =>
        Servers.FirstOrDefault(x => string.Equals(x.Name, name, StringComparison.OrdinalIgnoreCase));

    /// <summary>增量對齊清單，保留既有物件與選取狀態</summary>
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

    private void TriggerBackgroundSizeBackfill()
    {
        var token = _sizeCalculation.Next();

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
                        string formatted = bytes <= 0 ? "-" : UnitFormatter.FormatBytes(bytes);

                        _ui.PostToUi(() =>
                        {
                            if (ct.IsCancellationRequested)
                            {
                                return;
                            }

                            // 大小只顯示於清單列，不需重算選取詳情
                            target.Row.RawSizeBytes = bytes;
                            target.Row.Size = formatted;
                        });
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        Logger.Warning(ex, "非同步計算伺服器目錄大小失敗（{Path}）", target.Path);
                    }
                }).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                Logger.Information("伺服器目錄大小背景計算已取消");
            }
        }, token), "伺服器目錄大小背景計算", Logger);
    }
}
