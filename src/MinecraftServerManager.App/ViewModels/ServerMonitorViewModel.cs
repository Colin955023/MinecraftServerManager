using MinecraftServerManager.App.Services;
using System.Buffers;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器即時監控視窗 ViewModel
/// </summary>
public sealed partial class ServerMonitorViewModel : ObservableObject, IDisposable
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerMonitor");
    private readonly IServerRuntime _serverRuntime;
    private readonly IUiTimer _flushTimer;
    private readonly IUiTimer _statsTimer;
    private const int MaxBufferedLines = 5000;
    private readonly Queue<string> _logBuffer = new();
    private readonly Lock _bufferLock = new();
    private readonly string _serverPath;
    private readonly string _serverName;
    private DateTime? _startTime;
    private bool _serverReadyNotified;
    private Task _historyLoadTask = Task.CompletedTask;

    /// <summary>
    /// 歷史 latest.log 載入工作（供測試或需要等待載入完成的呼叫端使用）
    /// </summary>
    public Task HistoryLoadTask => _historyLoadTask;

    [GeneratedRegex(@"\x1B\[[0-?]*[ -/]*[@-~]")]
    private static partial Regex AnsiRegex();

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
    public partial bool IsServerRunning { get; set; }

    partial void OnIsServerRunningChanged(bool value)
    {
        OnPropertyChanged(nameof(CanStartServer));
    }

    public bool CanStartServer => !IsServerRunning;

    [ObservableProperty]
    public partial string ServerStatusText { get; set; } = "已停止";

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

    public ObservableCollection<string> OnlinePlayers { get; } = [];

    /// <summary>
    /// 是否無線上玩家
    /// </summary>
    public bool HasNoOnlinePlayers => OnlinePlayers.Count == 0;

    /// <summary>
    /// 伺服器啟動委派
    /// </summary>
    private readonly Func<Task>? _startRequestHandler;

    public ServerMonitorViewModel(
        IServerRuntime serverRuntime,
        string serverName,
        string serverPath = "",
        string mcVersion = "",
        Func<Task>? startRequestHandler = null,
        IUiService? uiService = null)
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _serverRuntime = serverRuntime;
        _serverName = serverName;
        _startRequestHandler = startRequestHandler;
        OnlinePlayers.CollectionChanged += (_, _) => OnPropertyChanged(nameof(HasNoOnlinePlayers));
        _serverPath = serverPath;
        MinecraftVersionText = string.IsNullOrWhiteSpace(mcVersion) ? "未知" : mcVersion;
        WindowTitle = $"伺服器主控台監控 — {serverName}";
        IsServerRunning = serverRuntime.IsRunning;

        if (IsServerRunning)
        {
            _startTime = DateTime.Now;
            ServerStatusText = _serverRuntime.IsReady ? "執行中 (已就緒)" : "啟動中 (載入世界)...";
            _serverReadyNotified = _serverRuntime.IsReady;
        }

        // 載入歷史 latest.log
        LoadLatestLogHistory();

        _serverRuntime.OutputLineReceived += OnOutputLineReceived;
        _serverRuntime.ServerStarted += OnServerStarted;
        _serverRuntime.ServerExited += OnServerExited;
        _serverRuntime.ServerReady += OnServerReady;

        _flushTimer = _ui.CreateUiTimer(TimeSpan.FromMilliseconds(50), OnFlushTimerTick);
        _flushTimer.StartTimer();

        _statsTimer = _ui.CreateUiTimer(TimeSpan.FromSeconds(1), OnStatsTimerTick);
        _statsTimer.StartTimer();
    }

    /// <summary>
    /// 手動重新整理並清空現有主控台紀錄，重新從磁碟載入最新 latest.log
    /// </summary>
    [RelayCommand]
    public void ReloadLogs()
    {
        lock (_bufferLock)
        {
            _logBuffer.Clear();
        }
        Logs.Clear();
        LoadLatestLogHistory();
    }

    private void LoadLatestLogHistory() => _historyLoadTask = LoadLatestLogHistoryAsync();

    /// <summary>
    /// 於背景執行緒讀取 latest.log 尾端內容，回到 UI 執行緒後合併至主控台（保留載入期間已收到的即時輸出）
    /// </summary>
    private async Task LoadLatestLogHistoryAsync()
    {
        if (string.IsNullOrWhiteSpace(_serverPath))
        {
            return;
        }

        string serverPath = _serverPath;
        List<string>? history = await Task.Run(() => ReadLatestLogTail(serverPath)).ConfigureAwait(true);
        if (history is null || history.Count == 0)
        {
            return;
        }

        Logs.ReplaceAll(history.Concat(Logs).ToList());
        Logger.Information("已載入歷史 latest.log，共 {Count} 行", Logs.Count);
    }

    /// <summary>
    /// 讀取 latest.log 尾端最多 2 MB、2500 行的內容並去除 ANSI 色碼；失敗或無檔案時回傳 null
    /// </summary>
    private static List<string>? ReadLatestLogTail(string serverPath)
    {
        string logFile = Path.Combine(serverPath, "logs", "latest.log");
        if (!File.Exists(logFile))
        {
            return null;
        }

        try
        {
            const int maxBytesToRead = 2 * 1024 * 1024;
            const int maxLines = 2500;

            using var fs = new FileStream(logFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            long length = fs.Length;
            if (length == 0)
            {
                return null;
            }

            long bytesToRead = Math.Min(length, maxBytesToRead);
            fs.Seek(-bytesToRead, SeekOrigin.End);

            byte[] buffer = ArrayPool<byte>.Shared.Rent((int)bytesToRead);
            string text;
            try
            {
                int bytesRead = fs.Read(buffer, 0, (int)bytesToRead);
                text = Encoding.UTF8.GetString(buffer, 0, bytesRead);
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(buffer);
            }

            var textSpan = text.AsSpan();
            int totalLines = 0;
            bool endsWithNewline = text.EndsWith('\n') || text.EndsWith('\r');
            bool lastLineEmpty = false;

            foreach (var lineSpan in textSpan.EnumerateLines())
            {
                totalLines++;
                lastLineEmpty = lineSpan.IsEmpty;
            }

            if (totalLines > 0 && lastLineEmpty && endsWithNewline)
            {
                totalLines--;
            }

            int startIndex = bytesToRead < length && totalLines > 1 ? 1 : 0;
            int takeCount = Math.Min(maxLines, totalLines - startIndex);
            int from = totalLines - takeCount;
            int first = Math.Max(startIndex, from);

            var result = new List<string>(Math.Max(0, totalLines - first));
            int currentIndex = 0;
            foreach (var lineSpan in textSpan.EnumerateLines())
            {
                if (currentIndex >= totalLines)
                {
                    break;
                }

                if (currentIndex >= first)
                {
                    string rawLine = lineSpan.ToString();
                    result.Add(AnsiRegex().Replace(rawLine, string.Empty).TrimStart('\uFEFF'));
                }

                currentIndex++;
            }

            return result;
        }
        catch (Exception ex)
        {
            Logger.Warning("讀取歷史 latest.log 失敗: {Message}", ex.Message);
            return null;
        }
    }

    private void OnStatsTimerTick()
    {
        IsServerRunning = _serverRuntime.IsRunning;
        if (IsServerRunning)
        {
            _startTime ??= DateTime.Now;
            var elapsed = DateTime.Now - _startTime.Value;
            UptimeText = $"{elapsed:hh\\:mm\\:ss}";

            if (_serverRuntime.Pid > 0)
            {
                int pid = _serverRuntime.Pid;
                try
                {
                    using var proc = Process.GetProcessById(pid);
                    long memMb = proc.WorkingSet64 / (1024 * 1024);
                    MemoryUsageText = $"{memMb} MB";
                }
                catch
                {
                    MemoryUsageText = "-";
                }
            }
        }
        else
        {
            MemoryUsageText = "-";
            ServerStatusText = "已停止";
        }
    }

    private readonly List<string> _commandHistory = [];
    private int _historyIndex = -1;
    private string _draftText = string.Empty;

    /// <summary>
    /// 鍵盤方向鍵上下瀏覽歷史傳送指令
    /// </summary>
    public string? NavigateHistory(bool previous)
    {
        if (_commandHistory.Count == 0)
        {
            return null;
        }

        if (previous)
        {
            if (_historyIndex == -1 || _historyIndex == _commandHistory.Count)
            {
                _draftText = CommandText;
                _historyIndex = _commandHistory.Count - 1;
            }
            else if (_historyIndex > 0)
            {
                _historyIndex--;
            }

            CommandText = _commandHistory[_historyIndex];
        }
        else
        {
            if (_historyIndex >= 0 && _historyIndex < _commandHistory.Count - 1)
            {
                _historyIndex++;
                CommandText = _commandHistory[_historyIndex];
            }
            else if (_historyIndex == _commandHistory.Count - 1)
            {
                _historyIndex = _commandHistory.Count;
                CommandText = _draftText;
            }
        }

        return CommandText;
    }

    /// <summary>
    /// 複製線上玩家名稱至系統剪貼簿
    /// </summary>
    [RelayCommand]
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

    [RelayCommand]
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
        ServerStatusText = IsServerRunning ? "執行中" : "已停止";
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
        _draftText = string.Empty;

        if (_commandHistory.Count == 0 || _commandHistory[^1] != cmd)
        {
            _commandHistory.Add(cmd);
        }
        _historyIndex = _commandHistory.Count;

        AddLogLine($"> {cmd}");
        Logger.Information("主控台傳送伺服器指令: {Command}", cmd);
        await _serverRuntime.SendCommandAsync(cmd).ConfigureAwait(false);
    }

    [RelayCommand]
    public async Task StartServerAsync()
    {
        if (_serverRuntime.IsRunning)
        {
            AddLogLine(">>> 伺服器已在執行中");
            return;
        }

        if (_startRequestHandler is null)
        {
            AddLogLine(">>> 此監控視窗未連動啟動功能，請回管理頁面啟動伺服器");
            return;
        }

        Logger.Information("主控台請求啟動伺服器");
        _serverReadyNotified = false;
        ServerStatusText = "啟動中 (載入世界)...";
        AddLogLine(">>> 正在啟動伺服器...");
        await _startRequestHandler().ConfigureAwait(true);
        RefreshState();
    }

    [RelayCommand]
    public async Task StopServerAsync()
    {
        if (!_serverRuntime.IsRunning)
        {
            return;
        }

        Logger.Information("主控台請求平順停止伺服器");
        ServerStatusText = "正在關閉伺服器...";
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

        Logger.Warning("主控台請求強制終止伺服器");
        ServerStatusText = "正在強制終止伺服器...";
        AddLogLine(">>> 強制終止伺服器行程...");
        await _serverRuntime.StopAsync(TimeSpan.Zero).ConfigureAwait(false);
    }

    [RelayCommand]
    public void ClearLogs()
    {
        lock (_bufferLock)
        {
            _logBuffer.Clear();
        }
        Logs.Clear();
    }

    private void OnOutputLineReceived(string rawLine)
    {
        string cleaned = AnsiRegex().Replace(rawLine, string.Empty).TrimEnd('\r', '\n');
        ProcessPlayerEvents(cleaned);

        lock (_bufferLock)
        {
            _logBuffer.Enqueue(cleaned);
            TrimLogBuffer();
        }
    }

    /// <summary>
    /// 限制待沖刷佇列容量，避免日誌洪峰造成記憶體暴增；呼叫端須已持有 <see cref="_bufferLock"/>。
    /// </summary>
    private void TrimLogBuffer()
    {
        while (_logBuffer.Count > MaxBufferedLines)
        {
            _logBuffer.Dequeue();
        }
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
            DispatchIfPossible(() =>
            {
                OnlinePlayersText = $"{current} / {max}";
                OnlinePlayers.Clear();
                foreach (string player in playersRaw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                {
                    OnlinePlayers.Add(player);
                }
                OnPropertyChanged(nameof(HasNoOnlinePlayers));
            });
        }

        if (line.Contains("joined the game", StringComparison.OrdinalIgnoreCase)
            && PlayerJoinRegex().Match(line) is { Success: true } joinMatch)
        {
            string player = joinMatch.Groups[1].Value;
            DispatchIfPossible(() =>
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
            DispatchIfPossible(() =>
            {
                OnlinePlayers.Remove(player);
                OnPropertyChanged(nameof(HasNoOnlinePlayers));
            });
        }
    }

    private void DispatchIfPossible(Action action) => _ui.RunOnUi(action);

    private void OnServerStarted()
    {
        DispatchIfPossible(() =>
        {
            IsServerRunning = true;
            _startTime = DateTime.Now;
            ServerStatusText = "啟動中 (載入世界)...";
            _serverReadyNotified = false;
            AddLogLine("[系統] 伺服器行程已啟動...");
            Logger.Information("主控台已接收伺服器啟動事件");
        });
    }

    private void OnServerReady()
    {
        DispatchIfPossible(() =>
        {
            if (IsServerRunning)
            {
                ServerStatusText = "執行中 (已就緒)";
                AddLogLine("[系統] 伺服器已就緒完成載入！");
                Logger.Information("主控台已接收伺服器就緒事件");

                if (!_serverReadyNotified)
                {
                    _serverReadyNotified = true;
                    _ = ShowServerReadyNotificationAsync();
                }
            }
        });
    }

    private async Task ShowServerReadyNotificationAsync()
    {
        try
        {
            string? serverPath = _serverPath;
            (string serverIp, string serverPort) = await Task.Run(() => ReadServerAddress(serverPath)).ConfigureAwait(true);

            string msg = !string.IsNullOrWhiteSpace(serverIp)
                ? $"伺服器 {_serverName} 啟動完成！\n已在 {serverIp}:{serverPort} 開啟服務"
                : $"伺服器 {_serverName} 啟動完成！\n已在連接埠 {serverPort} 開啟服務";

            _ui.ShowInfo(msg, "伺服器啟動成功");
        }
        catch (Exception ex)
        {
            Logger.Warning("顯示伺服器就緒通知失敗: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 讀取 server.properties 中的 server-ip 與 server-port，未設定或讀取失敗時使用預設值
    /// </summary>
    private static (string ServerIp, string ServerPort) ReadServerAddress(string? serverPath)
    {
        string serverPort = "25565";
        string serverIp = string.Empty;

        if (!string.IsNullOrWhiteSpace(serverPath))
        {
            string propsPath = Path.Combine(serverPath, "server.properties");
            if (File.Exists(propsPath))
            {
                try
                {
                    using var stream = new FileStream(propsPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                    using var reader = new StreamReader(stream, Encoding.UTF8);
                    string? line;
                    while ((line = reader.ReadLine()) is not null)
                    {
                        ReadOnlySpan<char> span = line.AsSpan().Trim();
                        if (span.IsEmpty || span.StartsWith("#") || span.StartsWith("!"))
                        {
                            continue;
                        }

                        int eq = span.IndexOf('=');
                        if (eq <= 0)
                        {
                            continue;
                        }

                        ReadOnlySpan<char> key = span[..eq].Trim();
                        ReadOnlySpan<char> val = span[(eq + 1)..].Trim();

                        if (key.Equals("server-port", StringComparison.OrdinalIgnoreCase) && !val.IsEmpty)
                        {
                            serverPort = val.ToString();
                        }
                        else if (key.Equals("server-ip", StringComparison.OrdinalIgnoreCase) && !val.IsEmpty)
                        {
                            serverIp = val.ToString();
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Information("讀取 server.properties 位址資訊時發生存取限制，降級採用預設連接埠：{Message}", ex.Message);
                }
            }
        }

        return (serverIp, serverPort);
    }

    private void OnServerExited(int exitCode)
    {
        DispatchIfPossible(() =>
        {
            IsServerRunning = false;
            ServerStatusText = $"已停止 (代碼: {exitCode})";
            OnlinePlayers.Clear();
            OnlinePlayersText = "0 / 20";
            MemoryUsageText = "-";
            UptimeText = "00:00:00";
            _startTime = null;
            AddLogLine($"[系統] 伺服器行程已結束，結束代碼：{exitCode}");
            Logger.Information("伺服器監控已捕捉伺服器結束事件，結束代碼: {ExitCode}", exitCode);
        });
    }

    private void OnFlushTimerTick()
    {
        List<string> batch = [];
        lock (_bufferLock)
        {
            while (_logBuffer.Count > 0)
            {
                batch.Add(_logBuffer.Dequeue());
            }
        }

        if (batch.Count == 0)
        {
            return;
        }

        const int maxLogs = 2000;
        if (Logs.Count + batch.Count <= maxLogs)
        {
            Logs.AddRange(batch);
        }
        else
        {
            Logs.ReplaceAll(Logs.Concat(batch).TakeLast(maxLogs).ToList());
        }
    }

    private void AddLogLine(string line)
    {
        lock (_bufferLock)
        {
            _logBuffer.Enqueue(line);
            TrimLogBuffer();
        }
    }

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
