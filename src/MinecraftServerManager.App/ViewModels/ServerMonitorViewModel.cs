using System.Diagnostics;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器即時監控視窗 ViewModel</summary>
public sealed partial class ServerMonitorViewModel : ViewModelBase, IDisposable
{
    private const int DisplayedLogsHighWatermark = 2200;
    private const int DisplayedLogsLowWatermark = 1800;
    private const int MaxCommandHistory = 100;
    private const int DefaultMaxPlayers = 20;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMonitorViewModel));

    private readonly IUiService _ui;
    private readonly IServerRuntime _serverRuntime;
    private readonly IServerLogReader _logReader;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly Func<Task> _startRequestHandler;
    private readonly IUiTimer _flushTimer;
    private readonly IUiTimer _statsTimer;

    // 超過高水位即修剪至低水位，緩衝只需比高水位多一行即可觸發修剪
    private readonly LogLineBuffer _logBuffer = new(DisplayedLogsHighWatermark + 1);
    private readonly ConsoleCommandHistory _commandHistory = new(MaxCommandHistory);
    private readonly string _serverPath;
    private readonly string _serverName;
    private long? _startTimestamp;
    private bool _serverReadyNotified;
    private int _logSessionId;
    private int _maxPlayers = DefaultMaxPlayers;
    private volatile bool _disposed;

    public ServerMonitorViewModel(
        IServerRuntime serverRuntime,
        IServerLogReader logReader,
        IServerPropertiesStore propertiesStore,
        string serverName,
        IUiService uiService,
        string serverPath,
        string mcVersion,
        ServerStopCoordinator stopCoordinator,
        Func<Task> startRequestHandler)
    {
        ArgumentNullException.ThrowIfNull(stopCoordinator);
        ArgumentNullException.ThrowIfNull(startRequestHandler);
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(logReader);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);

        _stopCoordinator = stopCoordinator;
        _startRequestHandler = startRequestHandler;
        _ui = uiService;
        _serverRuntime = serverRuntime;
        _logReader = logReader;
        _propertiesStore = propertiesStore;
        _serverName = serverName;
        _serverPath = serverPath;

        OnlinePlayers.CollectionChanged += (_, _) => OnPropertyChanged(nameof(HasNoOnlinePlayers));
        MinecraftVersionText = string.IsNullOrWhiteSpace(mcVersion) ? "未知" : mcVersion;
        WindowTitle = $"伺服器主控台監控 — {serverName}";
        IsServerRunning = serverRuntime.IsRunning;

        if (IsServerRunning)
        {
            // 由執行階段的啟動時間還原運行時間，重開監控視窗不歸零
            _startTimestamp = serverRuntime.StartedTimestamp ?? Stopwatch.GetTimestamp();
            _serverReadyNotified = _serverRuntime.IsReady;
        }
        else
        {
            // 執行中的 latest.log 會被即時輸出取代，僅於停止狀態載入歷史
            _ = RunSafeAsync(LoadLatestLogHistoryAsync, "載入歷史 latest.log", Logger);
        }

        _serverRuntime.OutputLineReceived += OnOutputLineReceived;
        _serverRuntime.ServerStarted += OnServerStarted;
        _serverRuntime.ServerExited += OnServerExited;
        _serverRuntime.ServerReady += OnServerReady;

        _flushTimer = _ui.CreateUiTimer(TimeSpan.FromMilliseconds(100), OnFlushTimerTick);
        _statsTimer = _ui.CreateUiTimer(TimeSpan.FromSeconds(1), OnStatsTimerTick);
        if (IsServerRunning)
        {
            StartTimers();
        }
    }

    public string WindowTitle { get; }

    [ObservableProperty]
    public partial string CommandText { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanStartServer))]
    [NotifyCanExecuteChangedFor(nameof(StartServerCommand), nameof(StopServerCommand), nameof(SendCommandCommand), nameof(ForceKillCommand))]
    public partial bool IsServerRunning { get; set; }

    public bool CanStartServer => !IsServerRunning;

    [ObservableProperty]
    public partial string OnlinePlayersText { get; set; } = "0 / 20";

    [ObservableProperty]
    public partial string MemoryUsageText { get; set; } = "-";

    public string MinecraftVersionText { get; } = "-";

    [ObservableProperty]
    public partial string UptimeText { get; set; } = "00:00:00";

    [ObservableProperty]
    public partial bool IsAutoScrollEnabled { get; set; } = true;

    public BulkObservableCollection<string> Logs { get; } = [];

    public BulkObservableCollection<string> OnlinePlayers { get; } = [];

    public bool HasNoOnlinePlayers => OnlinePlayers.Count == 0;

    /// <summary>啟動畫面更新計時器；已處置後不再啟動</summary>
    private void StartTimers()
    {
        if (_disposed)
        {
            return;
        }

        _flushTimer.StartTimer();
        _statsTimer.StartTimer();
    }

    /// <summary>背景讀取 latest.log 尾端並合併至主控台</summary>
    private async Task LoadLatestLogHistoryAsync()
    {
        if (string.IsNullOrWhiteSpace(_serverPath))
        {
            return;
        }

        int currentSession = _logSessionId;
        IReadOnlyList<string> history = await _logReader.ReadLatestLogTailAsync(_serverPath);
        if (_disposed || history.Count == 0)
        {
            return;
        }

        RunOnUiIfAlive(() =>
        {
            if (currentSession != _logSessionId || IsServerRunning)
            {
                // 載入期間伺服器已啟動或日誌已清除時，丟棄舊歷史
                return;
            }

            string[] combined = [.. history, .. Logs];
            Logs.ReplaceAll(combined.Length > DisplayedLogsHighWatermark ? combined[^DisplayedLogsLowWatermark..] : combined);
            Logger.Information("已載入歷史 latest.log，共 {Count} 行", Logs.Count);
        });
    }

    /// <summary>格式化運行時間；小時數不以 24 取餘</summary>
    public static string FormatUptime(TimeSpan elapsed) =>
        $"{(int)elapsed.TotalHours:D2}:{elapsed.Minutes:D2}:{elapsed.Seconds:D2}";

    private void OnStatsTimerTick()
    {
        if (_disposed)
        {
            return;
        }

        IsServerRunning = _serverRuntime.IsRunning;
        if (IsServerRunning)
        {
            _startTimestamp ??= _serverRuntime.StartedTimestamp ?? Stopwatch.GetTimestamp();
            UptimeText = FormatUptime(Stopwatch.GetElapsedTime(_startTimestamp.Value));

            long? workingSet = _serverRuntime.GetWorkingSet64();
            MemoryUsageText = workingSet.HasValue ? UnitFormatter.FormatBytes(workingSet.Value) : "-";
        }
        else
        {
            MemoryUsageText = "-";
        }
    }

    /// <summary>複製線上玩家名稱至系統剪貼簿</summary>
    [RelayCommand]
    private void CopyPlayerName(string? playerName)
    {
        if (string.IsNullOrWhiteSpace(playerName))
        {
            return;
        }

        string name = playerName.Trim();
        _ui.CopyToClipboard(name);
        AddLogLine($"[系統] 已複製玩家名稱「{name}」至剪貼簿");
        Logger.Information("已複製玩家名稱至剪貼簿");
    }

    /// <summary>複製主控台全部紀錄至系統剪貼簿</summary>
    [RelayCommand]
    private void CopyAllLogs()
    {
        if (Logs.Count > 0)
        {
            _ui.CopyToClipboard(string.Join(Environment.NewLine, Logs));
            Logger.Information("已將主控台全部紀錄複製至剪貼簿");
        }
    }

    [RelayCommand]
    public void RefreshState()
    {
        if (_disposed)
        {
            return;
        }

        IsServerRunning = _serverRuntime.IsRunning;
        if (IsServerRunning)
        {
            StartTimers();
        }
        Logger.Information("手動重新整理監控視窗狀態");
    }

    [RelayCommand(CanExecute = nameof(IsServerRunning))]
    public async Task SendCommandAsync()
    {
        if (string.IsNullOrWhiteSpace(CommandText))
        {
            return;
        }

        string cmd = CommandText.Trim();
        CommandText = string.Empty;
        _commandHistory.Add(cmd);

        AddLogLine($"> {cmd}");
        try
        {
            await _serverRuntime.SendCommandAsync(cmd);
        }
        catch (Exception ex) when (ProcessControlExceptions.IsExpected(ex))
        {
            Logger.Warning(ex, "傳送主控台指令失敗");
            AddLogLine($"[系統] 指令傳送失敗：{ex.Message}");
        }
    }

    /// <summary>瀏覽已傳送的指令；離開歷史時還原草稿，無歷史回傳 null</summary>
    public string? NavigateHistory(bool previous)
    {
        if (_commandHistory.Navigate(previous, CommandText) is not { } text)
        {
            return null;
        }

        CommandText = text;
        return text;
    }

    [RelayCommand(CanExecute = nameof(CanStartServer))]
    public async Task StartServerAsync()
    {
        if (_serverRuntime.IsRunning)
        {
            AddLogLine(">>> 伺服器已在執行中");
            return;
        }

        Logger.Information("主控台請求啟動伺服器");
        _serverReadyNotified = false;
        AddLogLine(">>> 正在啟動伺服器...");
        await _startRequestHandler();
        RefreshState();
    }

    [RelayCommand(CanExecute = nameof(IsServerRunning))]
    public async Task StopServerAsync()
    {
        if (!_serverRuntime.IsRunning)
        {
            return;
        }

        Logger.Information("主控台請求平順停止伺服器");
        AddLogLine(">>> 傳送 stop 指令停止伺服器...");
        await _stopCoordinator.StopAsync(_serverName);
    }

    [RelayCommand(CanExecute = nameof(IsServerRunning))]
    public async Task ForceKillAsync()
    {
        if (!_serverRuntime.IsRunning)
        {
            return;
        }

        Logger.Information("主控台請求強制終止伺服器");
        AddLogLine(">>> 強制終止伺服器行程...");
        await _serverRuntime.StopAsync(TimeSpan.Zero);
    }

    [RelayCommand]
    public void ClearLogs()
    {
        Interlocked.Increment(ref _logSessionId);
        _logBuffer.Clear();
        Logs.Clear();
    }

    /// <summary>於背景執行緒接收輸出；不讀取 UI 屬性，改以執行階段狀態判斷</summary>
    private void OnOutputLineReceived(string rawLine)
    {
        if (_disposed)
        {
            return;
        }

        string cleaned = ModHelpers.StripColorAndFormattingCodes(rawLine).TrimEnd('\r', '\n');
        ProcessPlayerEvents(cleaned);
        _logBuffer.Post(cleaned);
        if (!_serverRuntime.IsRunning)
        {
            RunOnUiIfAlive(OnFlushTimerTick);
        }
    }

    private void ProcessPlayerEvents(string line)
    {
        if (ServerPlayerLogParser.TryParsePlayerList(line) is { } list)
        {
            RunOnUiIfAlive(() =>
            {
                if (list.MaxPlayers is int value)
                {
                    _maxPlayers = value;
                }

                OnlinePlayersText = $"{list.OnlineCount} / {_maxPlayers}";
                OnlinePlayers.ReplaceAll(list.Players);
            });
        }

        if (ServerPlayerLogParser.TryParseJoin(line) is { } player)
        {
            RunOnUiIfAlive(() =>
            {
                if (IndexOfPlayer(player) < 0)
                {
                    OnlinePlayers.Add(player);
                    UpdateOnlinePlayersText();
                }
            });
        }

        if (ServerPlayerLogParser.TryParseLeave(line) is { } leftPlayer)
        {
            RunOnUiIfAlive(() =>
            {
                int index = IndexOfPlayer(leftPlayer);
                if (index >= 0)
                {
                    OnlinePlayers.RemoveAt(index);
                    UpdateOnlinePlayersText();
                }
            });
        }
    }

    /// <summary>玩家名稱不分大小寫比對</summary>
    private int IndexOfPlayer(string player)
    {
        for (int i = 0; i < OnlinePlayers.Count; i++)
        {
            if (string.Equals(OnlinePlayers[i], player, StringComparison.OrdinalIgnoreCase))
            {
                return i;
            }
        }

        return -1;
    }

    private void UpdateOnlinePlayersText() => OnlinePlayersText = $"{OnlinePlayers.Count} / {_maxPlayers}";

    /// <summary>派送至 UI 執行緒；執行時已處置則略過</summary>
    private void RunOnUiIfAlive(Action action) => _ui.RunOnUi(() =>
    {
        if (!_disposed)
        {
            action();
        }
    });

    private void OnServerStarted(int pid)
    {
        _ = pid;
        RunOnUiIfAlive(() =>
        {
            ClearLogs();
            IsServerRunning = true;
            _startTimestamp = _serverRuntime.StartedTimestamp ?? Stopwatch.GetTimestamp();
            _serverReadyNotified = false;
            StartTimers();
            AddLogLine("[系統] 伺服器行程已啟動...");
            Logger.Information("主控台已接收伺服器啟動事件");
        });
    }

    private void OnServerReady()
    {
        RunOnUiIfAlive(() =>
        {
            if (IsServerRunning)
            {
                AddLogLine("[系統] 伺服器已就緒，完成載入！");
                Logger.Information("主控台已接收伺服器就緒事件");

                if (!_serverReadyNotified)
                {
                    _serverReadyNotified = true;
                    _ = RunSafeAsync(ShowServerReadyNotificationAsync, "伺服器就緒通知", Logger);
                }
            }
        });
    }

    private async Task ShowServerReadyNotificationAsync()
    {
        try
        {
            (string serverIp, string serverPort) = await ServerPropertiesAddressHelper.ReadAddressAsync(_propertiesStore, _serverName);

            string msg = !string.IsNullOrWhiteSpace(serverIp)
                ? $"伺服器 {_serverName} 啟動完成！\n已在 {serverIp}:{serverPort} 開啟服務"
                : $"伺服器 {_serverName} 啟動完成！\n已在連接埠 {serverPort} 開啟服務";

            _ui.ShowNotification(msg, $"伺服器啟動成功 — {_serverName}", NotificationType.Success);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("顯示伺服器就緒通知已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "顯示伺服器就緒通知失敗");
        }
    }

    private void OnServerExited(int exitCode)
    {
        RunOnUiIfAlive(() =>
        {
            IsServerRunning = false;
            OnlinePlayers.Clear();
            UpdateOnlinePlayersText();
            MemoryUsageText = "-";
            UptimeText = "00:00:00";
            _startTimestamp = null;
            AddLogLine($"[系統] 伺服器行程已結束，結束代碼：{exitCode}");
            OnFlushTimerTick();
            _flushTimer.StopTimer();
            _statsTimer.StopTimer();
            Logger.Information("伺服器監控已捕捉伺服器結束事件，結束代碼：{ExitCode}", exitCode);
        });
    }

    private void OnFlushTimerTick()
    {
        if (_disposed)
        {
            return;
        }

        _logBuffer.FlushTo(Logs, DisplayedLogsHighWatermark, DisplayedLogsLowWatermark);
    }

    private void AddLogLine(string line)
    {
        _logBuffer.Post(line);
        if (!IsServerRunning)
        {
            OnFlushTimerTick();
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _flushTimer.Dispose();
        _statsTimer.Dispose();
        _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
        _serverRuntime.ServerStarted -= OnServerStarted;
        _serverRuntime.ServerExited -= OnServerExited;
        _serverRuntime.ServerReady -= OnServerReady;
    }
}
