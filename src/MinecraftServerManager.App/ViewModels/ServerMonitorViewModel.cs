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
    private readonly object _bufferLock = new();
    private readonly string _serverPath;
    private DateTime? _startTime;

    [GeneratedRegex(@"\x1B\[[0-?]*[ -/]*[@-~]")]
    private static partial Regex AnsiRegex();

    [GeneratedRegex(@"There are (\d+) of a max (\d+) players online", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerCountRegex();

    [GeneratedRegex(@":\s*(\w+)\s+joined the game", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerJoinRegex();

    [GeneratedRegex(@":\s*(\w+)\s+left the game", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerLeaveRegex();

    [ObservableProperty]
    private string _windowTitle;

    [ObservableProperty]
    private string _commandText = string.Empty;

    [ObservableProperty]
    private bool _isServerRunning;

    [ObservableProperty]
    private string _serverStatusText = "已停止";

    [ObservableProperty]
    private string _onlinePlayersText = "0 / 20";

    [ObservableProperty]
    private string _jvmPidText = "-";

    [ObservableProperty]
    private string _memoryUsageText = "-";

    [ObservableProperty]
    private string _minecraftVersionText = "-";

    [ObservableProperty]
    private string _uptimeText = "00:00:00";

    [ObservableProperty]
    private bool _isAutoScrollEnabled = true;

    public ObservableCollection<string> Logs { get; } = [];

    public ObservableCollection<string> OnlinePlayers { get; } = [];

    public ServerMonitorViewModel(
        IServerRuntime serverRuntime,
        string serverName,
        string serverPath = "",
        string mcVersion = "")
    {
        _serverRuntime = serverRuntime;
        _serverPath = serverPath;
        _minecraftVersionText = string.IsNullOrWhiteSpace(mcVersion) ? "未知" : mcVersion;
        _windowTitle = $"伺服器主控台監控 — {serverName}";
        _isServerRunning = serverRuntime.IsRunning;

        if (_isServerRunning)
        {
            _startTime = DateTime.Now;
            _serverStatusText = "執行中";
            _jvmPidText = _serverRuntime.Pid > 0 ? $"PID: {_serverRuntime.Pid}" : "-";
        }

        // 載入歷史 latest.log
        LoadLatestLogHistory();

        _serverRuntime.OutputLineReceived += OnOutputLineReceived;
        _serverRuntime.ServerExited += OnServerExited;

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

    private void LoadLatestLogHistory()
    {
        if (string.IsNullOrWhiteSpace(_serverPath))
        {
            return;
        }

        string logFile = Path.Combine(_serverPath, "logs", "latest.log");
        if (File.Exists(logFile))
        {
            try
            {
                var lines = File.ReadLines(logFile, Encoding.UTF8).TakeLast(200);
                foreach (string line in lines)
                {
                    string cleaned = AnsiRegex().Replace(line, string.Empty);
                    Logs.Add(cleaned);
                }
                Logger.Information("已載入歷史 latest.log，共 {Count} 行", Logs.Count);
            }
            catch (Exception ex)
            {
                Logger.Warning("讀取歷史 latest.log 失敗: {Message}", ex.Message);
            }
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
                JvmPidText = $"PID: {pid}";
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
            JvmPidText = "-";
            MemoryUsageText = "-";
            ServerStatusText = "已停止";
        }
    }

    [RelayCommand]
    public void RefreshState()
    {
        IsServerRunning = _serverRuntime.IsRunning;
        ServerStatusText = IsServerRunning ? "執行中" : "已停止";
        Logger.Information("手動刷新監控視窗狀態");
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
        Logger.Information("主控台發送伺服器指令: {Command}", cmd);
        await _serverRuntime.SendCommandAsync(cmd).ConfigureAwait(false);
    }

    [RelayCommand]
    public async Task StopServerAsync()
    {
        Logger.Information("主控台請求優雅停止伺服器");
        ServerStatusText = "正在關閉伺服器...";
        AddLogLine(">>> 發送 stop 命令停止伺服器...");
        await _serverRuntime.StopAsync(TimeSpan.FromSeconds(15)).ConfigureAwait(false);
    }

    [RelayCommand]
    public async Task ForceKillAsync()
    {
        Logger.Warning("主控台請求強制終止伺服器");
        ServerStatusText = "正在強制終止伺服器...";
        AddLogLine(">>> 強制終止伺服器處理程序...");
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

        var match = PlayerCountRegex().Match(cleaned);
        if (match.Success)
        {
            string current = match.Groups[1].Value;
            string max = match.Groups[2].Value;
            OnlinePlayersText = $"{current} / {max}";
        }

        var joinMatch = PlayerJoinRegex().Match(cleaned);
        if (joinMatch.Success)
        {
            string player = joinMatch.Groups[1].Value;
            if (!OnlinePlayers.Contains(player))
            {
                System.Windows.Application.Current.Dispatcher.Invoke(() => OnlinePlayers.Add(player));
            }
        }

        var leaveMatch = PlayerLeaveRegex().Match(cleaned);
        if (leaveMatch.Success)
        {
            string player = leaveMatch.Groups[1].Value;
            System.Windows.Application.Current.Dispatcher.Invoke(() => OnlinePlayers.Remove(player));
        }

        lock (_bufferLock)
        {
            _logBuffer.Enqueue(cleaned);
        }
    }

    private void OnServerExited(int exitCode)
    {
        IsServerRunning = false;
        ServerStatusText = $"已停止 (代碼: {exitCode})";
        AddLogLine($"[系統] 伺服器程序已結束，結束代碼：{exitCode}");
        Logger.Information("伺服器監控已捕獲伺服器結束事件，退出代碼: {ExitCode}", exitCode);
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
        if (overflow > 0)
        {
            int removeCount = Math.Min(overflow, Logs.Count);
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
        _serverRuntime.ServerExited -= OnServerExited;
    }
}
