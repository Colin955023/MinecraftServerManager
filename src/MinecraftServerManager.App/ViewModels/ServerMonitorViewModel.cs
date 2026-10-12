using System.Buffers;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器即時監控視窗 ViewModel
/// </summary>
public sealed partial class ServerMonitorViewModel : ObservableObject, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerMonitor");
    private readonly IServerRuntime _serverRuntime;
    private readonly DispatcherTimer _flushTimer;
    private readonly DispatcherTimer _statsTimer;
    private readonly Queue<string> _logBuffer = new();
    private readonly Lock _bufferLock = new();
    private readonly string _serverPath;
    private readonly string _serverName;
    private DateTime? _startTime;
    private bool _serverReadyNotified;

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
    public ObservableCollection<string> Logs { get; } = [];

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
        Func<Task>? startRequestHandler = null)
    {
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

        _flushTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(50)
        };
        _flushTimer.Tick += OnFlushTimerTick;
        _flushTimer.Start();

        _statsTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(1)
        };
        _statsTimer.Tick += OnStatsTimerTick;
        _statsTimer.Start();
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

    private void LoadLatestLogHistory()
    {
        if (string.IsNullOrWhiteSpace(_serverPath))
        {
            return;
        }

        string logFile = Path.Combine(_serverPath, "logs", "latest.log");
        if (!File.Exists(logFile))
        {
            return;
        }

        try
        {
            const int maxBytesToRead = 2 * 1024 * 1024;
            const int maxLines = 2500;

            using var fs = new FileStream(logFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            long length = fs.Length;
            if (length == 0)
            {
                return;
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
            var keptLines = new List<string>(maxLines);
            foreach (var lineSpan in text.AsSpan().EnumerateLines())
            {
                keptLines.Add(lineSpan.ToString());
            }

            if (keptLines.Count > 0 && string.IsNullOrEmpty(keptLines[^1]) && (text.EndsWith('\n') || text.EndsWith('\r')))
            {
                keptLines.RemoveAt(keptLines.Count - 1);
            }

            int startIndex = bytesToRead < length && keptLines.Count > 1 ? 1 : 0;
            int takeCount = Math.Min(maxLines, keptLines.Count - startIndex);
            int from = keptLines.Count - takeCount;

            for (int i = Math.Max(startIndex, from); i < keptLines.Count; i++)
            {
                string cleaned = AnsiRegex().Replace(keptLines[i], string.Empty).TrimStart('\uFEFF');
                Logs.Add(cleaned);
            }

            Logger.Information("已載入歷史 latest.log，共 {Count} 行", Logs.Count);
        }
        catch (Exception ex)
        {
            Logger.Warning("讀取歷史 latest.log 失敗: {Message}", ex.Message);
        }
    }

    private void OnStatsTimerTick(object? sender, EventArgs e)
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
            System.Windows.Clipboard.SetText(playerName.Trim());
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
            System.Windows.Clipboard.SetText(text);
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

        var listMatch = PlayerListRegex().Match(cleaned);
        if (listMatch.Success)
        {
            string current = listMatch.Groups[1].Value;
            string max = listMatch.Groups[2].Success && !string.IsNullOrWhiteSpace(listMatch.Groups[2].Value)
                ? listMatch.Groups[2].Value
                : "20";
            OnlinePlayersText = $"{current} / {max}";

            string playersRaw = listMatch.Groups[3].Value.Trim();
            DispatchIfPossible(() =>
            {
                OnlinePlayers.Clear();
                if (!string.IsNullOrWhiteSpace(playersRaw))
                {
                    string[] players = playersRaw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                    foreach (string player in players)
                    {
                        if (!string.IsNullOrWhiteSpace(player))
                        {
                            OnlinePlayers.Add(player);
                        }
                    }
                }
                OnPropertyChanged(nameof(HasNoOnlinePlayers));
            });
        }

        var joinMatch = PlayerJoinRegex().Match(cleaned);
        if (joinMatch.Success)
        {
            string player = joinMatch.Groups[1].Value;
            if (!OnlinePlayers.Contains(player))
            {
                DispatchIfPossible(() =>
                {
                    OnlinePlayers.Add(player);
                    OnPropertyChanged(nameof(HasNoOnlinePlayers));
                });
            }
        }

        var leaveMatch = PlayerLeaveRegex().Match(cleaned);
        if (leaveMatch.Success)
        {
            string player = leaveMatch.Groups[1].Value;
            DispatchIfPossible(() =>
            {
                OnlinePlayers.Remove(player);
                OnPropertyChanged(nameof(HasNoOnlinePlayers));
            });
        }

        lock (_bufferLock)
        {
            _logBuffer.Enqueue(cleaned);
        }
    }

    private static void DispatchIfPossible(Action action)
    {
        if (System.Windows.Application.Current?.Dispatcher is { } dispatcher && !dispatcher.CheckAccess())
        {
            dispatcher.Invoke(action);
        }
        else
        {
            action();
        }
    }

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
                    ShowServerReadyNotification();
                }
            }
        });
    }

    private void ShowServerReadyNotification()
    {
        try
        {
            string serverPort = "25565";
            string serverIp = string.Empty;

            if (!string.IsNullOrWhiteSpace(_serverPath))
            {
                string propsPath = Path.Combine(_serverPath, "server.properties");
                if (File.Exists(propsPath))
                {
                    foreach (string line in File.ReadLines(propsPath))
                    {
                        string trimmed = line.Trim();
                        if (trimmed.StartsWith('#') || !trimmed.Contains('='))
                        {
                            continue;
                        }
                        string[] parts = trimmed.Split('=', 2);
                        string key = parts[0].Trim();
                        string val = parts[1].Trim();
                        if (key.Equals("server-port", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(val))
                        {
                            serverPort = val;
                        }
                        else if (key.Equals("server-ip", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(val))
                        {
                            serverIp = val;
                        }
                    }
                }
            }

            string msg = !string.IsNullOrWhiteSpace(serverIp)
                ? $"伺服器 {_serverName} 啟動完成！\n已在 {serverIp}:{serverPort} 開啟服務"
                : $"伺服器 {_serverName} 啟動完成！\n已在連接埠 {serverPort} 開啟服務";

            System.Windows.MessageBox.Show(msg, "伺服器啟動成功", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            Logger.Warning("顯示伺服器就緒通知失敗: {Message}", ex.Message);
        }
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

    private void OnFlushTimerTick(object? sender, EventArgs e)
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
        int overflow = Logs.Count + batch.Count - maxLogs;
        if (overflow >= Logs.Count)
        {
            Logs.Clear();
        }
        else if (overflow > 0)
        {
            int removeCount = Math.Min(overflow, Logs.Count);
            if (removeCount > 40)
            {
                var remaining = Logs.Skip(removeCount).Concat(batch).ToList();
                Logs.Clear();
                foreach (string? line in remaining)
                {
                    Logs.Add(line);
                }
                return;
            }

            for (int i = 0; i < removeCount; i++)
            {
                Logs.RemoveAt(0);
            }
        }

        foreach (string line in batch)
        {
            Logs.Add(line);
        }
    }

    private void AddLogLine(string line)
    {
        lock (_bufferLock)
        {
            _logBuffer.Enqueue(line);
        }
    }

    public void Dispose()
    {
        _flushTimer.Stop();
        _statsTimer.Stop();
        _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
        _serverRuntime.ServerStarted -= OnServerStarted;
        _serverRuntime.ServerExited -= OnServerExited;
        _serverRuntime.ServerReady -= OnServerReady;
    }
}
