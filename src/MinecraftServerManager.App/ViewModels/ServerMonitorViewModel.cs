using MinecraftServerManager.App.Services;
using System.Diagnostics;
using System.Text.RegularExpressions;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器即時監控視窗 ViewModel
/// </summary>
public sealed partial class ServerMonitorViewModel : ViewModelBase, IDisposable
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMonitorViewModel));
    private readonly IServerRuntime _serverRuntime;
    private readonly IServerLogReader _logReader;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly IUiTimer _flushTimer;
    private readonly IUiTimer _statsTimer;
    private const int MaxBufferedLines = 5000;
    private const int DisplayedLogsHighWatermark = 2200;
    private const int DisplayedLogsLowWatermark = 1800;
    private readonly LogLineBuffer _logBuffer = new(MaxBufferedLines);
    private readonly string _serverPath;
    private readonly string _serverName;
    private long? _startTimestamp;
    private bool _serverReadyNotified;
    private int _logSessionId;

    /// <summary>
    /// 取得目前監控之伺服器名稱
    /// </summary>
    public string ServerName => _serverName;

    [GeneratedRegex(@"(?i)There are\s+(\d+)(?:\s*(?:of a max(?: of)?|/)\s*(\d+))?\s+players online:?\s*(.*)$")]
    private static partial Regex PlayerListRegex();

    [GeneratedRegex(@":\s*(\w+)\s+joined the game", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerJoinRegex();

    [GeneratedRegex(@":\s*(\w+)\s+left the game", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerLeaveRegex();

    [ObservableProperty]
    public partial string WindowTitle { get; set; }

    [ObservableProperty]
    public partial string CommandText { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanStartServer))]
    [NotifyCanExecuteChangedFor(nameof(StartServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopServerCommand))]
    public partial bool IsServerRunning { get; set; }

    public bool CanStartServer => !IsServerRunning;

    [ObservableProperty]
    public partial string OnlinePlayersText { get; set; } = "0 / 20";

    [ObservableProperty]
    public partial string MemoryUsageText { get; set; } = "-";

    [ObservableProperty]
    public partial string MinecraftVersionText { get; set; } = "-";

    [ObservableProperty]
    public partial string UptimeText { get; set; } = "00:00:00";

    [ObservableProperty]
    public partial bool IsAutoScrollEnabled { get; set; } = true;
    public BulkObservableCollection<string> Logs { get; } = [];

    public BulkObservableCollection<string> OnlinePlayers { get; } = [];

    /// <summary>
    /// 是否無線上玩家
    /// </summary>
    public bool HasNoOnlinePlayers => OnlinePlayers.Count == 0;

    /// <summary>
    /// 伺服器啟動委派
    /// </summary>
    private readonly Func<Task> _startRequestHandler;

    public ServerMonitorViewModel(
        IServerRuntime serverRuntime,
        IServerLogReader logReader,
        IServerPropertiesStore propertiesStore,
        string serverName,
        IUiService uiService,
        string serverPath,
        string mcVersion,
        Func<Task> startRequestHandler)
    {
        ArgumentNullException.ThrowIfNull(startRequestHandler);
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(logReader);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        _ui = uiService;
        _serverRuntime = serverRuntime;
        _logReader = logReader;
        _propertiesStore = propertiesStore;
        _serverName = serverName;
        _startRequestHandler = startRequestHandler;
        OnlinePlayers.CollectionChanged += (_, _) => OnPropertyChanged(nameof(HasNoOnlinePlayers));
        _serverPath = serverPath;
        MinecraftVersionText = string.IsNullOrWhiteSpace(mcVersion) ? "未知" : mcVersion;
        WindowTitle = $"伺服器主控台監控 — {serverName}";
        IsServerRunning = serverRuntime.IsRunning;

        if (IsServerRunning)
        {
            _startTimestamp = Stopwatch.GetTimestamp();
            _serverReadyNotified = _serverRuntime.IsReady;
        }

        // 載入歷史 latest.log
        _ = RunSafeAsync(LoadLatestLogHistoryAsync, "載入歷史 latest.log", Logger);

        _serverRuntime.OutputLineReceived += OnOutputLineReceived;
        _serverRuntime.ServerStarted += OnServerStarted;
        _serverRuntime.ServerExited += OnServerExited;
        _serverRuntime.ServerReady += OnServerReady;

        _flushTimer = _ui.CreateUiTimer(TimeSpan.FromMilliseconds(100), OnFlushTimerTick);
        _flushTimer.StartTimer();

        _statsTimer = _ui.CreateUiTimer(TimeSpan.FromSeconds(1), OnStatsTimerTick);
        _statsTimer.StartTimer();
    }

    /// <summary>
    /// 於背景執行緒讀取 latest.log 尾端內容，回到 UI 執行緒後合併至主控台（保留載入期間已收到的即時輸出）
    /// </summary>
    private async Task LoadLatestLogHistoryAsync()
    {
        if (string.IsNullOrWhiteSpace(_serverPath))
        {
            return;
        }

        int currentSession = _logSessionId;
        IReadOnlyList<string> history = await _logReader.ReadLatestLogTailAsync(_serverPath).ConfigureAwait(true);
        if (history.Count == 0)
        {
            return;
        }

        if (currentSession != _logSessionId || IsServerRunning)
        {
            // 若在載入歷史紀錄期間伺服器已啟動或使用者已清理日誌，丟棄舊歷史紀錄，避免覆蓋清空後的輸出
            return;
        }

        string[] combined = [.. history, .. Logs];
        Logs.ReplaceAll(combined.Length > DisplayedLogsHighWatermark ? combined[^DisplayedLogsLowWatermark..] : combined);
        Logger.Information("已載入歷史 latest.log，共 {Count} 行", Logs.Count);
    }

    private void OnStatsTimerTick()
    {
        IsServerRunning = _serverRuntime.IsRunning;
        if (IsServerRunning)
        {
            _startTimestamp ??= Stopwatch.GetTimestamp();
            var elapsed = Stopwatch.GetElapsedTime(_startTimestamp.Value);
            UptimeText = $"{elapsed:hh\\:mm\\:ss}";

            long? workingSet = _serverRuntime.GetWorkingSet64();
            MemoryUsageText = workingSet.HasValue ? UnitFormatter.FormatBytes(workingSet.Value) : "-";
        }
        else
        {
            MemoryUsageText = "-";
        }
    }

    /// <summary>
    /// 複製線上玩家名稱至系統剪貼簿
    /// </summary>
    public void CopyPlayerName(string? playerName)
    {
        if (string.IsNullOrWhiteSpace(playerName))
        {
            return;
        }

        try
        {
            _ui.CopyToClipboard(playerName.Trim());
            AddLogLine($"[系統] 已複製玩家名稱「{playerName.Trim()}」至剪貼簿");
            Logger.Information("已複製玩家名稱至剪貼簿: {PlayerName}", playerName);
        }
        catch (Exception ex)
        {
            Logger.Warning("複製玩家名稱至剪貼簿失敗：{Message}", ex.Message);
        }
    }

    public void CopyAllLogs()
    {
        if (Logs.Count == 0)
        {
            return;
        }

        try
        {
            string text = string.Join(Environment.NewLine, Logs);
            _ui.CopyToClipboard(text);
            Logger.Information("已將主控台全部紀錄複製至剪貼簿");
        }
        catch (Exception ex)
        {
            Logger.Warning("複製紀錄失敗：{Message}", ex.Message);
        }
    }

    [RelayCommand]
    public void RefreshState()
    {
        IsServerRunning = _serverRuntime.IsRunning;
        Logger.Information("手動重新整理監控視窗狀態");
    }

    [RelayCommand]
    public async Task SendCommandAsync()
    {
        if (string.IsNullOrWhiteSpace(CommandText))
        {
            return;
        }

        string cmd = CommandText.Trim();
        CommandText = string.Empty;

        AddLogLine($"> {cmd}");
        Logger.Information("主控台傳送伺服器指令: {Command}", cmd);
        await _serverRuntime.SendCommandAsync(cmd).ConfigureAwait(false);
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
        await _startRequestHandler().ConfigureAwait(true);
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
        await _serverRuntime.StopAsync(TimeSpan.FromSeconds(15)).ConfigureAwait(false);
    }

    [RelayCommand]
    public async Task ForceKillAsync()
    {
        if (!_serverRuntime.IsRunning)
        {
            return;
        }

        Logger.Information("主控台請求強制終止伺服器");
        AddLogLine(">>> 強制終止伺服器行程...");
        await _serverRuntime.StopAsync(TimeSpan.Zero).ConfigureAwait(false);
    }

    [RelayCommand]
    public void ClearLogs()
    {
        Interlocked.Increment(ref _logSessionId);
        _logBuffer.Clear();
        Logs.Clear();
    }

    private void OnOutputLineReceived(string rawLine)
    {
        string cleaned = ModHelpers.StripColorAndFormattingCodes(rawLine).TrimEnd('\r', '\n');
        ProcessPlayerEvents(cleaned);
        _logBuffer.Post(cleaned);
    }

    /// <summary>
    /// 先以字串包含判斷排除絕大多數無關行，僅對可能符合的行執行正規表示式
    /// </summary>
    private void ProcessPlayerEvents(string line)
    {
        if (line.Contains("players online", StringComparison.OrdinalIgnoreCase)
            && PlayerListRegex().Match(line) is { Success: true } listMatch)
        {
            string current = listMatch.Groups[1].Value;
            string max = listMatch.Groups[2].Success && !string.IsNullOrWhiteSpace(listMatch.Groups[2].Value)
                ? listMatch.Groups[2].Value
                : "20";
            string playersRaw = listMatch.Groups[3].Value.Trim();
            _ui.RunOnUi(() =>
            {
                OnlinePlayersText = $"{current} / {max}";
                string[] parsedPlayers = playersRaw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                OnlinePlayers.ReplaceAll(parsedPlayers);
                OnPropertyChanged(nameof(HasNoOnlinePlayers));
            });
        }

        if (line.Contains("joined the game", StringComparison.OrdinalIgnoreCase)
            && PlayerJoinRegex().Match(line) is { Success: true } joinMatch)
        {
            string player = joinMatch.Groups[1].Value;
            _ui.RunOnUi(() =>
            {
                if (!OnlinePlayers.Contains(player))
                {
                    OnlinePlayers.Add(player);
                    OnPropertyChanged(nameof(HasNoOnlinePlayers));
                }
            });
        }

        if (line.Contains("left the game", StringComparison.OrdinalIgnoreCase)
            && PlayerLeaveRegex().Match(line) is { Success: true } leaveMatch)
        {
            string player = leaveMatch.Groups[1].Value;
            _ui.RunOnUi(() =>
            {
                OnlinePlayers.Remove(player);
                OnPropertyChanged(nameof(HasNoOnlinePlayers));
            });
        }
    }

    private void OnServerStarted()
    {
        _ui.RunOnUi(() =>
        {
            ClearLogs();
            IsServerRunning = true;
            _startTimestamp = Stopwatch.GetTimestamp();
            _serverReadyNotified = false;
            AddLogLine("[系統] 伺服器行程已啟動...");
            Logger.Information("主控台已接收伺服器啟動事件");
        });
    }

    private void OnServerReady()
    {
        _ui.RunOnUi(() =>
        {
            if (IsServerRunning)
            {
                AddLogLine("[系統] 伺服器已就緒完成載入！");
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
            (string serverIp, string serverPort) = await ReadServerAddressAsync().ConfigureAwait(true);

            string msg = !string.IsNullOrWhiteSpace(serverIp)
                ? $"伺服器 {_serverName} 啟動完成！\n已在 {serverIp}:{serverPort} 開啟服務"
                : $"伺服器 {_serverName} 啟動完成！\n已在連接埠 {serverPort} 開啟服務";

            _ui.ShowNotification(msg, $"伺服器啟動成功 — {_serverName}", NotificationType.Success);
        }
        catch (Exception ex)
        {
            Logger.Warning("顯示伺服器就緒通知失敗: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 經由 server.properties 存取服務讀取 server-ip 與 server-port，未設定或讀取失敗時使用預設值
    /// </summary>
    private async Task<(string ServerIp, string ServerPort)> ReadServerAddressAsync()
    {
        string serverPort = ServerDefaults.DefaultPort;
        string serverIp = string.Empty;
        try
        {
            var snapshot = await _propertiesStore.ReadAsync(_serverName).ConfigureAwait(true);
            if (snapshot.Properties.TryGetValue("server-port", out string? port) && !string.IsNullOrWhiteSpace(port))
            {
                serverPort = port.Trim();
            }

            if (snapshot.Properties.TryGetValue("server-ip", out string? ip) && !string.IsNullOrWhiteSpace(ip))
            {
                serverIp = ip.Trim();
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("讀取 server.properties 位址資訊失敗，降級採用預設連接埠：{Message}", ex.Message);
        }

        return (serverIp, serverPort);
    }

    private void OnServerExited(int exitCode)
    {
        _ui.RunOnUi(() =>
        {
            IsServerRunning = false;
            OnlinePlayers.Clear();
            OnlinePlayersText = "0 / 20";
            MemoryUsageText = "-";
            UptimeText = "00:00:00";
            _startTimestamp = null;
            AddLogLine($"[系統] 伺服器行程已結束，結束代碼：{exitCode}");
            Logger.Information("伺服器監控已捕捉伺服器結束事件，結束代碼: {ExitCode}", exitCode);
        });
    }

    private void OnFlushTimerTick() => _logBuffer.FlushTo(Logs, DisplayedLogsHighWatermark, DisplayedLogsLowWatermark);

    private void AddLogLine(string line) => _logBuffer.Post(line);

    public void Dispose()
    {
        _flushTimer.StopTimer();
        _statsTimer.StopTimer();
        _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
        _serverRuntime.ServerStarted -= OnServerStarted;
        _serverRuntime.ServerExited -= OnServerExited;
        _serverRuntime.ServerReady -= OnServerReady;
    }
}
