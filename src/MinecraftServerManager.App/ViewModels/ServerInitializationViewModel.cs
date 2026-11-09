using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 初始化倒數計時顯示狀態
/// </summary>
public enum InitializationCountdownState
{
    None,
    Success,
    Warning,
}

/// <summary>
/// 伺服器初次啟動初始化視窗 ViewModel：執行初始化流程、彙整主控台輸出與倒數自動關閉
/// </summary>
public sealed partial class ServerInitializationViewModel : ViewModelBase, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInitializationViewModel));

    /// <summary>
    /// 主控台文字長度上限，超過時修剪至 <see cref="TrimmedConsoleChars"/>
    /// </summary>
    public const int MaxConsoleChars = 50000;

    /// <summary>
    /// 主控台修剪後保留字元數
    /// </summary>
    public const int TrimmedConsoleChars = 40000;

    private const int MaxPendingLines = 5000;
    private const int MaxLinesPerFlush = 500;

    private readonly IUiService _ui;
    private readonly IServerRuntime _serverRuntime;
    private readonly ServerInitializationWorkflow _workflow;
    private readonly ServerConfig _config;
    private readonly string _javaExecutablePath;
    private readonly LogLineBuffer _pendingLines = new(MaxPendingLines);
    private readonly List<string> _flushBatch = [];
    private IUiTimer? _flushTimer;
    private IUiTimer? _countdownTimer;
    private bool _isClosingExpected;
    private bool _isStopping;
    private bool _subscribed;

    [ObservableProperty]
    public partial string TitleText { get; set; }

    [ObservableProperty]
    public partial string StatusText { get; set; } = "狀態：正在準備啟動伺服器執行初次世界生成與設定...";

    [ObservableProperty]
    public partial string ConsoleText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsProgressVisible { get; set; } = true;

    [ObservableProperty]
    public partial string CountdownText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial InitializationCountdownState CountdownState { get; set; }

    [ObservableProperty]
    public partial int CountdownSeconds { get; set; }

    [ObservableProperty]
    public partial string CompleteButtonText { get; set; } = "完成初始化";

    [ObservableProperty]
    public partial bool IsCompleteEnabled { get; set; }

    /// <summary>
    /// 初始化是否成功完成
    /// </summary>
    public bool IsSuccess { get; private set; }

    /// <summary>
    /// 要求視窗關閉
    /// </summary>
    public event Action? CloseRequested;

    public ServerInitializationViewModel(
        IServerRuntime serverRuntime,
        IServerLaunchPlanner launchPlanner,
        ServerConfig config,
        string javaExecutablePath,
        IUiService uiService)
    {
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(config);

        _ui = uiService;
        _serverRuntime = serverRuntime;
        _config = config;
        _javaExecutablePath = javaExecutablePath;
        _workflow = new ServerInitializationWorkflow(serverRuntime, launchPlanner);
        TitleText = $"正在初始化伺服器「{config.Name.Value}」";
    }

    /// <summary>
    /// 訂閱伺服器輸出並啟動初始化流程（視窗載入後呼叫）
    /// </summary>
    public async Task StartAsync()
    {
        try
        {
            _serverRuntime.OutputLineReceived += OnOutputLineReceived;
            _serverRuntime.ServerReady += OnServerReady;
            _serverRuntime.ServerExited += OnServerExited;
            _subscribed = true;

            _flushTimer = _ui.CreateUiTimer(TimeSpan.FromMilliseconds(150), FlushPendingLines);
            _flushTimer.StartTimer();

            AppendLog($"[系統] 準備啟動伺服器「{_config.Name.Value}」執行初次世界與設定初始化...\n");

            string executableName = await Task.Run(() => ServerInitializationWorkflow.ResolveExecutableName(_config.Path)).ConfigureAwait(true);
            AppendLog(executableName.EndsWith(".bat", StringComparison.OrdinalIgnoreCase)
                ? $"[系統] 偵測到啟動腳本 {executableName}，即將執行...\n"
                : $"[系統] 啟動伺服器核心 {executableName}...\n");

            await _workflow.StartAsync(_javaExecutablePath, _config, executableName).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器初次啟動初始化操作已由使用者取消。");
            StatusText = "狀態：初始化操作已取消";
            EnableClose();
            IsSuccess = false;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "初次啟動伺服器失敗: {Message}", ex.Message);
            AppendLog($"[錯誤] 伺服器啟動失敗: {ex.Message}\n");
            StatusText = "狀態：啟動伺服器時發生例外錯誤，請檢查輸出";
            EnableClose();
            IsSuccess = false;
            StartCountdown(60, isSuccess: false);
        }
    }

    /// <summary>
    /// 使用者取消初始化
    /// </summary>
    public void Cancel()
    {
        IsSuccess = false;
        CloseRequested?.Invoke();
    }

    /// <summary>
    /// 使用者確認完成初始化
    /// </summary>
    public void Complete()
    {
        IsSuccess = true;
        CloseRequested?.Invoke();
    }

    /// <summary>
    /// 視窗即將關閉時呼叫；伺服器仍在執行時回傳 true 以攔截關閉，並於平順停止後再次要求關閉
    /// </summary>
    public bool HandleClosing()
    {
        StopTimersAndUnsubscribe();
        if (!_serverRuntime.IsRunning || _isClosingExpected)
        {
            return false;
        }

        if (!_isStopping)
        {
            _ = RunSafeAsync(StopThenCloseAsync, "停止初始化伺服器", Logger);
        }

        return true;
    }

    private async Task StopThenCloseAsync()
    {
        _isStopping = true;
        try
        {
            await _workflow.StopAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("關閉視窗時停止伺服器發生例外: {Message}", ex.Message);
        }
        finally
        {
            _isStopping = false;
        }

        _isClosingExpected = true;
        CloseRequested?.Invoke();
    }

    private void OnOutputLineReceived(string line) => _pendingLines.Post(line);

    private void OnServerReady() => _ui.PostToUi(() =>
    {
        FlushPendingLines();
        StatusText = "狀態：伺服器已就緒！正在平順關閉完成初始化...";
        AppendLog("\n[系統] 伺服器準備完畢，所有模組載入完成，正在傳送 stop 指令正常關閉...\n");
    });

    private void OnServerExited(int exitCode) => _ui.PostToUi(() => HandleServerExited(exitCode));

    /// <summary>
    /// 依是否已偵測到就緒訊號更新結束狀態並啟動倒數
    /// </summary>
    public void HandleServerExited(int exitCode)
    {
        FlushPendingLines();
        IsProgressVisible = false;
        EnableClose();
        if (_workflow.ReadyDetected)
        {
            IsSuccess = true;
            StatusText = "狀態：伺服器初次啟動初始化完成！";
            AppendLog($"\n[系統] 伺服器行程已安全結束（結束代碼：{exitCode}），初次初始化完成！\n");
            CompleteButtonText = "完成初始化";
            StartCountdown(2, isSuccess: true);
        }
        else
        {
            IsSuccess = false;
            StatusText = $"狀態：伺服器未完成初始化即結束（代碼：{exitCode}）";
            AppendLog($"\n[警告] 伺服器行程已結束（結束代碼：{exitCode}），未收到就緒標記。\n");
            StartCountdown(60, isSuccess: false);
        }
    }

    private void EnableClose()
    {
        IsCompleteEnabled = true;
        CompleteButtonText = "關閉";
    }

    private void StartCountdown(int seconds, bool isSuccess)
    {
        _countdownTimer?.StopTimer();
        CountdownSeconds = seconds;
        CountdownState = isSuccess ? InitializationCountdownState.Success : InitializationCountdownState.Warning;
        UpdateCountdownText();

        _countdownTimer = _ui.CreateUiTimer(TimeSpan.FromSeconds(1), OnCountdownTick);
        _countdownTimer.StartTimer();
    }

    private void OnCountdownTick()
    {
        CountdownSeconds--;
        UpdateCountdownText();
        if (CountdownSeconds <= 0)
        {
            _countdownTimer?.StopTimer();
            _isClosingExpected = true;
            CloseRequested?.Invoke();
        }
    }

    private void UpdateCountdownText() =>
        CountdownText = CountdownState == InitializationCountdownState.Success
            ? $"初始化完成！倒數 {CountdownSeconds} 秒後自動進入管理頁面..."
            : $"初始化未完成，倒數 {CountdownSeconds} 秒後自動關閉...";

    private void AppendLog(string text) => ConsoleText = AppendWithLimit(ConsoleText, text);

    /// <summary>
    /// 附加主控台文字；總長超過上限時僅保留尾端 <see cref="TrimmedConsoleChars"/> 字元
    /// </summary>
    public static string AppendWithLimit(string current, string text)
    {
        ArgumentNullException.ThrowIfNull(current);
        ArgumentNullException.ThrowIfNull(text);
        if (current.Length + text.Length > MaxConsoleChars)
        {
            current = current[^Math.Min(current.Length, TrimmedConsoleChars)..];
        }

        return current + text;
    }

    /// <summary>
    /// 排出待處理輸出（每次最多 500 行）並依關鍵字更新狀態文字
    /// </summary>
    public void FlushPendingLines()
    {
        _flushBatch.Clear();
        if (_pendingLines.DrainTo(_flushBatch, MaxLinesPerFlush) == 0)
        {
            return;
        }

        var batch = new StringBuilder();
        string? statusText = null;
        foreach (string line in _flushBatch)
        {
            batch.AppendLine(line);
            statusText = DetectStatus(line) ?? statusText;
        }

        _flushBatch.Clear();
        AppendLog(batch.ToString());
        if (statusText is not null)
        {
            StatusText = statusText;
        }
    }

    /// <summary>
    /// 依伺服器輸出關鍵字推斷目前初始化階段，無對應時回傳 null
    /// </summary>
    public static string? DetectStatus(string line)
    {
        ArgumentNullException.ThrowIfNull(line);
        if (line.Contains("Loading dimension", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Preparing spawn area", StringComparison.OrdinalIgnoreCase))
        {
            return "狀態：準備世界與生成區域中...";
        }

        return line.Contains("Preparing level", StringComparison.OrdinalIgnoreCase)
            ? "狀態：載入世界中..."
            : null;
    }

    private void StopTimersAndUnsubscribe()
    {
        _countdownTimer?.StopTimer();
        _flushTimer?.StopTimer();
        if (_subscribed)
        {
            _serverRuntime.OutputLineReceived -= OnOutputLineReceived;
            _serverRuntime.ServerReady -= OnServerReady;
            _serverRuntime.ServerExited -= OnServerExited;
            _subscribed = false;
        }
    }

    public void Dispose()
    {
        StopTimersAndUnsubscribe();
        _workflow.Dispose();
    }
}
