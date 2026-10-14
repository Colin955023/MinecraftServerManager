using System.Collections.Concurrent;
using System.ComponentModel;
using System.Text;
using System.Windows;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器初次啟動初始化對話方塊
/// </summary>
public sealed partial class ServerInitializationDialog : Window, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerInitialization");

    private readonly IServerRuntime _serverRuntime;
    private readonly ServerInitializationWorkflow _workflow;
    private readonly ServerConfig _config;
    private readonly string _javaExecutablePath;
    private const int MaxConsoleChars = 50000;
    private const int TrimmedConsoleChars = 40000;
    private const int MaxPendingLines = 5000;
    private const int MaxLinesPerFlush = 500;

    private readonly ConcurrentQueue<string> _pendingLines = new();
    private System.Windows.Threading.DispatcherTimer? _flushTimer;
    private System.Windows.Threading.DispatcherTimer? _countdownTimer;
    private int _countdownSeconds;
    private bool _isClosingExpected;

    public bool IsSuccess { get; private set; }

    public ServerInitializationDialog(
        IServerRuntime serverRuntime,
        ServerConfig config,
        string javaExecutablePath)
    {
        InitializeComponent();
        _serverRuntime = serverRuntime ?? throw new ArgumentNullException(nameof(serverRuntime));
        _config = config ?? throw new ArgumentNullException(nameof(config));
        _javaExecutablePath = javaExecutablePath;
        _workflow = new ServerInitializationWorkflow(serverRuntime);

        TitleText.Text = $"正在初始化伺服器「{_config.Name.Value}」";

        if (Icon == null)
        {
            try
            {
                Icon = System.Windows.Media.Imaging.BitmapFrame.Create(
                    new Uri("pack://application:,,,/MinecraftServerManager.App;component/assets/icon.ico", UriKind.RelativeOrAbsolute));
            }
            catch
            {
            }
        }

        Loaded += ServerInitializationDialog_Loaded;
        Closing += ServerInitializationDialog_Closing;
    }

    private async void ServerInitializationDialog_Loaded(object sender, RoutedEventArgs e)
    {
        _serverRuntime.OutputLineReceived += OnOutputLineReceived;
        _serverRuntime.ServerReady += OnServerReady;
        _serverRuntime.ServerExited += OnServerExited;

        _flushTimer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        _flushTimer.Tick += (_, _) => FlushPendingLines();
        _flushTimer.Start();

        AppendLog($"[系統] 準備啟動伺服器「{_config.Name.Value}」進行初次世界與設定初始化...\n");

        try
        {
            string executableName = await ServerInitializationWorkflow.ResolveStartupTargetAsync(_config).ConfigureAwait(true);
            AppendLog(executableName.EndsWith(".bat", StringComparison.OrdinalIgnoreCase)
                ? $"[系統] 偵測到啟動腳本 {executableName}，即將執行...\n"
                : $"[系統] 啟動伺服器核心 {executableName}...\n");

            await _workflow.StartAsync(_javaExecutablePath, _config, executableName).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "初次啟動伺服器失敗: {Message}", ex.Message);
            AppendLog($"[錯誤] 伺服器啟動失敗: {ex.Message}\n");
            StatusText.Text = "狀態: 啟動伺服器時發生例外錯誤，請檢查輸出";
            CompleteButton.IsEnabled = true;
            CompleteButton.Content = "關閉";
            IsSuccess = false;
            StartCountdown(60, isSuccess: false);
        }
    }

    private void OnOutputLineReceived(string line)
    {
        _pendingLines.Enqueue(line);
        while (_pendingLines.Count > MaxPendingLines && _pendingLines.TryDequeue(out _))
        {
        }
    }

    private void OnServerReady() => Dispatcher.InvokeAsync(() =>
    {
        FlushPendingLines();
        StatusText.Text = "狀態: 伺服器已就緒！正在平順關閉完成初始化...";
        AppendLog("\n[系統] 伺服器準備完畢，所有模組載入完成，正在傳送 stop 指令正常關閉...\n");
    });

    private void OnServerExited(int exitCode)
    {
        Dispatcher.InvokeAsync(() =>
        {
            FlushPendingLines();
            InitProgressBar.Visibility = Visibility.Collapsed;
            if (_workflow.ReadyDetected)
            {
                IsSuccess = true;
                StatusText.Text = "狀態: 伺服器初次啟動初始化完成！";
                AppendLog($"\n[系統] 伺服器行程已安全結束 (結束代碼: {exitCode})，初次初始化完成！\n");
                CompleteButton.IsEnabled = true;
                CompleteButton.Content = "完成初始化";
                StartCountdown(2, isSuccess: true);
            }
            else
            {
                IsSuccess = false;
                StatusText.Text = $"狀態: 伺服器未完成初始化即結束 (代碼: {exitCode})";
                AppendLog($"\n[警告] 伺服器行程已結束 (結束代碼: {exitCode})，未收到就緒標記。\n");
                CompleteButton.IsEnabled = true;
                CompleteButton.Content = "關閉";
                StartCountdown(60, isSuccess: false);
            }
        });
    }

    private void StartCountdown(int seconds, bool isSuccess)
    {
        _countdownTimer?.Stop();
        _countdownSeconds = seconds;
        UpdateCountdownDisplay(isSuccess);

        _countdownTimer = new System.Windows.Threading.DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(1)
        };
        _countdownTimer.Tick += (s, e) =>
        {
            _countdownSeconds--;
            UpdateCountdownDisplay(isSuccess);
            if (_countdownSeconds <= 0)
            {
                _countdownTimer?.Stop();
                _isClosingExpected = true;
                Close();
            }
        };
        _countdownTimer.Start();
    }

    private void UpdateCountdownDisplay(bool isSuccess)
    {
        if (isSuccess)
        {
            CountdownText.Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x00, 0xFF, 0x66));
            CountdownText.Text = $"初始化完成！倒數 {_countdownSeconds} 秒後自動進入管理頁面...";
        }
        else
        {
            CountdownText.Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xF5, 0x9E, 0x0B));
            CountdownText.Text = $"初始化未完成，倒數 {_countdownSeconds} 秒後自動關閉...";
        }
    }

    private void AppendLog(string text)
    {
        ConsoleBox.AppendText(text);
        if (ConsoleBox.Text.Length > MaxConsoleChars)
        {
            ConsoleBox.Text = ConsoleBox.Text[^TrimmedConsoleChars..];
        }
        ConsoleBox.CaretIndex = ConsoleBox.Text.Length;
        ConsoleBox.ScrollToEnd();
    }

    private void FlushPendingLines()
    {
        if (_pendingLines.IsEmpty)
        {
            return;
        }

        var batch = new StringBuilder();
        string? statusText = null;
        int taken = 0;
        while (taken < MaxLinesPerFlush && _pendingLines.TryDequeue(out string? line))
        {
            taken++;
            batch.AppendLine(line);
            if (line.Contains("Loading dimension", StringComparison.OrdinalIgnoreCase) ||
                line.Contains("Preparing spawn area", StringComparison.OrdinalIgnoreCase))
            {
                statusText = "狀態: 準備世界與生成區域中...";
            }
            else if (line.Contains("Preparing level", StringComparison.OrdinalIgnoreCase))
            {
                statusText = "狀態: 載入世界中...";
            }
        }

        AppendLog(batch.ToString());
        if (statusText is not null)
        {
            StatusText.Text = statusText;
        }
    }

    private async void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            _countdownTimer?.Stop();
            IsSuccess = false;

            if (_serverRuntime.IsRunning)
            {
                AppendLog("\n[系統] 使用者要求強制中斷伺服器...\n");
                StatusText.Text = "狀態: 正在強制終止伺服器...";
                CancelButton.IsEnabled = false;

                try
                {
                    await _workflow.StopAsync(TimeSpan.Zero);
                }
                catch (Exception ex)
                {
                    Logger.Warning("強制終止伺服器時發生例外: {Message}", ex.Message);
                }
            }

            _isClosingExpected = true;
            Close();
        }
        catch (Exception ex)
        {
            Logger.Warning("CancelButton_Click 異常: {Message}", ex.Message);
        }
    }

    private void CompleteButton_Click(object sender, RoutedEventArgs e)
    {
        _countdownTimer?.Stop();
        _isClosingExpected = true;
        Close();
    }

    private async void ServerInitializationDialog_Closing(object? sender, CancelEventArgs e)
    {
        try
        {
            _countdownTimer?.Stop();
            _flushTimer?.Stop();
            _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
            _serverRuntime.ServerReady -= OnServerReady;
            _serverRuntime.ServerExited -= OnServerExited;

            if (_serverRuntime.IsRunning && !_isClosingExpected)
            {
                e.Cancel = true;
                try
                {
                    await _workflow.StopAsync(TimeSpan.FromSeconds(5));
                }
                catch
                {
                }
                _isClosingExpected = true;
                Close();
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("ServerInitializationDialog_Closing 異常: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 釋放初次啟動流程資源（取消就緒事件訂閱）
    /// </summary>
    public void Dispose() => _workflow.Dispose();

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        try
        {
            if (Owner is not null)
            {
                if (Owner.WindowState == WindowState.Minimized)
                {
                    Owner.WindowState = WindowState.Normal;
                }
                Owner.Activate();
                Owner.Focus();
            }
        }
        catch
        {
        }
    }
}
