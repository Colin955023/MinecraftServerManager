using System.ComponentModel;
using System.IO;
using System.Text;
using System.Windows;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器初次啟動初始化對話框
/// </summary>
public partial class ServerInitializationDialog : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerInitialization");

    private readonly IServerRuntime _serverRuntime;
    private readonly ServerConfig _config;
    private readonly string _javaExecutablePath;
    private readonly StringBuilder _consoleBuffer = new();
    private System.Windows.Threading.DispatcherTimer? _countdownTimer;
    private int _countdownSeconds;
    private bool _doneDetected;
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

        AppendLog($"[系統] 準備啟動伺服器「{_config.Name.Value}」進行初次世界與設定初始化...\n");

        try
        {
            string startBat = Path.Combine(_config.Path, "start_server.bat");
            string runBat = Path.Combine(_config.Path, "run.bat");
            if (File.Exists(startBat))
            {
                AppendLog("[系統] 偵測到統一啟動腳本 start_server.bat，即將執行...\n");
                await _serverRuntime.StartAsync(
                    javaExecutablePath: _javaExecutablePath,
                    serverDirectory: _config.Path,
                    executableName: "start_server.bat",
                    memoryMaxMb: _config.MemoryMaxMb,
                    memoryMinMb: _config.MemoryMinMb,
                    customJvmArgs: _config.JvmArgs).ConfigureAwait(true);
            }
            else if (File.Exists(runBat))
            {
                AppendLog("[系統] 偵測到啟動腳本 run.bat，即將執行...\n");
                await _serverRuntime.StartAsync(
                    javaExecutablePath: _javaExecutablePath,
                    serverDirectory: _config.Path,
                    executableName: "run.bat",
                    memoryMaxMb: _config.MemoryMaxMb,
                    memoryMinMb: _config.MemoryMinMb,
                    customJvmArgs: _config.JvmArgs).ConfigureAwait(true);
            }
            else
            {
                string jarName = "server.jar";
                if (!File.Exists(Path.Combine(_config.Path, jarName)))
                {
                    string[] jars = Directory.GetFiles(_config.Path, "*.jar");
                    if (jars.Length > 0)
                    {
                        jarName = Path.GetFileName(jars[0]);
                    }
                }

                AppendLog($"[系統] 啟動伺服器核心 {jarName}...\n");
                await _serverRuntime.StartAsync(
                    javaExecutablePath: _javaExecutablePath,
                    serverDirectory: _config.Path,
                    executableName: jarName,
                    memoryMaxMb: _config.MemoryMaxMb,
                    memoryMinMb: _config.MemoryMinMb,
                    customJvmArgs: _config.JvmArgs).ConfigureAwait(true);
            }
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
        Dispatcher.InvokeAsync(() =>
        {
            AppendLog(line + Environment.NewLine);

            if (line.Contains("Loading dimension", StringComparison.OrdinalIgnoreCase) ||
                line.Contains("Preparing spawn area", StringComparison.OrdinalIgnoreCase))
            {
                StatusText.Text = "狀態: 準備世界與生成區域中...";
            }
            else if (line.Contains("Preparing level", StringComparison.OrdinalIgnoreCase))
            {
                StatusText.Text = "狀態: 載入世界中...";
            }
        });
    }

    private async void OnServerReady()
    {
        try
        {
            _doneDetected = true;
            await Dispatcher.InvokeAsync(async () =>
            {
                StatusText.Text = "狀態: 伺服器已就緒！正在優雅關閉完成初始化...";
                AppendLog("\n[系統] 伺服器準備完畢，所有模組載入完成，正在發送 stop 指令正常關閉...\n");

                try
                {
                    await _serverRuntime.StopAsync(TimeSpan.FromSeconds(30));
                }
                catch (Exception ex)
                {
                    Logger.Warning("發送 stop 指令或終止程序時發生異常: {Message}", ex.Message);
                }
            });
        }
        catch (Exception ex)
        {
            Logger.Warning("OnServerReady 異常: {Message}", ex.Message);
        }
    }

    private void OnServerExited(int exitCode)
    {
        Dispatcher.InvokeAsync(() =>
        {
            if (_doneDetected)
            {
                IsSuccess = true;
                StatusText.Text = "狀態: 伺服器初次啟動初始化完成！";
                AppendLog($"\n[系統] 伺服器程序已安全退出 (結束代碼: {exitCode})，初次初始化完成！\n");
                CompleteButton.IsEnabled = true;
                CompleteButton.Content = "完成初始化";
                StartCountdown(5, isSuccess: true);
            }
            else
            {
                IsSuccess = false;
                StatusText.Text = $"狀態: 伺服器未完成初始化即退出 (代碼: {exitCode})";
                AppendLog($"\n[警告] 伺服器程序已結束 (結束代碼: {exitCode})，未收到就緒標記。\n");
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
            CountdownText.Text = $"初始化未完成，倒數 {_countdownSeconds} 秒後自動退出...";
        }
    }

    private void AppendLog(string text)
    {
        _consoleBuffer.Append(text);
        if (_consoleBuffer.Length > 50000)
        {
            _consoleBuffer.Remove(0, 10000);
        }
        ConsoleBox.Text = _consoleBuffer.ToString();
        ConsoleBox.CaretIndex = ConsoleBox.Text.Length;
        ConsoleBox.ScrollToEnd();
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
                    await _serverRuntime.StopAsync(TimeSpan.Zero);
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
            _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
            _serverRuntime.ServerReady -= OnServerReady;
            _serverRuntime.ServerExited -= OnServerExited;

            if (_serverRuntime.IsRunning && !_isClosingExpected)
            {
                e.Cancel = true;
                try
                {
                    await _serverRuntime.StopAsync(TimeSpan.FromSeconds(5));
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
}
