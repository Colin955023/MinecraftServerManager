using System.Collections.Concurrent;
using System.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;
using Windows.UI;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器初次啟動初始化視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class ServerInitializationDialog : Window, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInitializationDialog));

    private static readonly SolidColorBrush SuccessCountdownBrush = new(Color.FromArgb(255, 0x00, 0xFF, 0x66));
    private static readonly SolidColorBrush WarningCountdownBrush = new(Color.FromArgb(255, 0xF5, 0x9E, 0x0B));

    private readonly IServerRuntime _serverRuntime;
    private readonly IUiService _ui;
    private readonly ServerInitializationWorkflow _workflow;
    private readonly ServerConfig _config;
    private readonly string _javaExecutablePath;
    private const int MaxConsoleChars = 50000;
    private const int TrimmedConsoleChars = 40000;
    private const int MaxPendingLines = 5000;
    private const int MaxLinesPerFlush = 500;

    private readonly ConcurrentQueue<string> _pendingLines = new();
    private IUiTimer? _flushTimer;
    private IUiTimer? _countdownTimer;
    private int _countdownSeconds;
    private bool _isClosingExpected;
    private bool _isStopping;

    public bool IsSuccess { get; private set; }

    public ServerInitializationDialog(
        IUiService ui,
        IServerRuntime serverRuntime,
        ServerConfig config,
        string javaExecutablePath)
    {
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(config);
        ArgumentNullException.ThrowIfNull(ui);
        InitializeComponent();
        Title = "伺服器初次啟動初始化";
        _ui = ui;
        _serverRuntime = serverRuntime;
        _config = config;
        _javaExecutablePath = javaExecutablePath;
        _workflow = new ServerInitializationWorkflow(serverRuntime);

        AppWindow.Resize(new Windows.Graphics.SizeInt32(780, 540));
        TitleText.Text = $"正在初始化伺服器「{_config.Name.Value}」";

        if (Content is FrameworkElement fe)
        {
            fe.Loaded += ServerInitializationDialog_Loaded;
        }

        AppWindow.Closing += ServerInitializationDialog_Closing;
    }

    private async void ServerInitializationDialog_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            _serverRuntime.OutputLineReceived += OnOutputLineReceived;
            _serverRuntime.ServerReady += OnServerReady;
            _serverRuntime.ServerExited += OnServerExited;

            _flushTimer = _ui.CreateUiTimer(TimeSpan.FromMilliseconds(150), FlushPendingLines);
            _flushTimer.StartTimer();

            AppendLog($"[系統] 準備啟動伺服器「{_config.Name.Value}」執行初次世界與設定初始化...\n");

            string executableName = SafeFileSystem.FileExists(Path.Combine(_config.Path, ServerDefaults.StartServerBatFileName))
                ? ServerDefaults.StartServerBatFileName
                : "server.jar";
            AppendLog(executableName.EndsWith(".bat", StringComparison.OrdinalIgnoreCase)
                ? $"[系統] 偵測到啟動腳本 {executableName}，即將執行...\n"
                : $"[系統] 啟動伺服器核心 {executableName}...\n");

            await _workflow.StartAsync(_javaExecutablePath, _config, executableName).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器初次啟動初始化操作已由使用者取消。");
            StatusText.Text = "狀態：初始化操作已取消";
            CompleteButton.IsEnabled = true;
            CompleteButton.Content = "關閉";
            IsSuccess = false;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "初次啟動伺服器失敗: {Message}", ex.Message);
            AppendLog($"[錯誤] 伺服器啟動失敗: {ex.Message}\n");
            StatusText.Text = "狀態：啟動伺服器時發生例外錯誤，請檢查輸出";
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

    private void OnServerReady() => _ui.PostToUi(() =>
    {
        FlushPendingLines();
        StatusText.Text = "狀態：伺服器已就緒！正在平順關閉完成初始化...";
        AppendLog("\n[系統] 伺服器準備完畢，所有模組載入完成，正在傳送 stop 指令正常關閉...\n");
    });

    private void OnServerExited(int exitCode)
    {
        _ui.PostToUi(() =>
        {
            FlushPendingLines();
            InitProgressBar.Visibility = Visibility.Collapsed;
            if (_workflow.ReadyDetected)
            {
                IsSuccess = true;
                StatusText.Text = "狀態：伺服器初次啟動初始化完成！";
                AppendLog($"\n[系統] 伺服器行程已安全結束（結束代碼：{exitCode}），初次初始化完成！\n");
                CompleteButton.IsEnabled = true;
                CompleteButton.Content = "完成初始化";
                StartCountdown(2, isSuccess: true);
            }
            else
            {
                IsSuccess = false;
                StatusText.Text = $"狀態：伺服器未完成初始化即結束（代碼：{exitCode}）";
                AppendLog($"\n[警告] 伺服器行程已結束（結束代碼：{exitCode}），未收到就緒標記。\n");
                CompleteButton.IsEnabled = true;
                CompleteButton.Content = "關閉";
                StartCountdown(60, isSuccess: false);
            }
        });
    }

    private void StartCountdown(int seconds, bool isSuccess)
    {
        _countdownTimer?.StopTimer();
        _countdownSeconds = seconds;
        UpdateCountdownDisplay(isSuccess);

        _countdownTimer = _ui.CreateUiTimer(TimeSpan.FromSeconds(1), () =>
        {
            _countdownSeconds--;
            UpdateCountdownDisplay(isSuccess);
            if (_countdownSeconds <= 0)
            {
                _countdownTimer?.StopTimer();
                _isClosingExpected = true;
                Close();
            }
        });
        _countdownTimer.StartTimer();
    }

    private void UpdateCountdownDisplay(bool isSuccess)
    {
        if (isSuccess)
        {
            CountdownText.Foreground = SuccessCountdownBrush;
            CountdownText.Text = $"初始化完成！倒數 {_countdownSeconds} 秒後自動進入管理頁面...";
        }
        else
        {
            CountdownText.Foreground = WarningCountdownBrush;
            CountdownText.Text = $"初始化未完成，倒數 {_countdownSeconds} 秒後自動關閉...";
        }
    }

    private void AppendLog(string text)
    {
        string current = ConsoleBox.Text;
        if (current.Length + text.Length > MaxConsoleChars)
        {
            int keepLen = Math.Min(current.Length, TrimmedConsoleChars);
            current = current[^keepLen..];
        }
        ConsoleBox.Text = current + text;
        ConsoleBox.SelectionStart = ConsoleBox.Text.Length;
        ConsoleScrollViewer.ChangeView(null, ConsoleScrollViewer.ScrollableHeight, null);
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
                statusText = "狀態：準備世界與生成區域中...";
            }
            else if (line.Contains("Preparing level", StringComparison.OrdinalIgnoreCase))
            {
                statusText = "狀態：載入世界中...";
            }
        }

        AppendLog(batch.ToString());
        if (statusText is not null)
        {
            StatusText.Text = statusText;
        }
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        IsSuccess = false;
        Close();
    }

    private void CompleteButton_Click(object sender, RoutedEventArgs e)
    {
        IsSuccess = true;
        Close();
    }

    private void CleanupTimersAndSubscriptions()
    {
        _countdownTimer?.StopTimer();
        _flushTimer?.StopTimer();
        _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
        _serverRuntime.ServerReady -= OnServerReady;
        _serverRuntime.ServerExited -= OnServerExited;
    }

    private async void ServerInitializationDialog_Closing(Microsoft.UI.Windowing.AppWindow sender, Microsoft.UI.Windowing.AppWindowClosingEventArgs args)
    {
        try
        {
            CleanupTimersAndSubscriptions();

            if (_serverRuntime.IsRunning && !_isClosingExpected)
            {
                args.Cancel = true;
                if (_isStopping)
                {
                    return;
                }

                _isStopping = true;
                try
                {
                    await _workflow.StopAsync(TimeSpan.FromSeconds(5));
                }
                catch (OperationCanceledException)
                {
                    Logger.Information("伺服器行程關閉等候已取消。");
                }
                catch (Exception ex)
                {
                    Logger.Warning("關閉對話方塊停止伺服器時發生例外: {Message}", ex.Message);
                }
                finally
                {
                    _isStopping = false;
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

    public void Dispose()
    {
        CleanupTimersAndSubscriptions();
        _workflow.Dispose();
    }
}
