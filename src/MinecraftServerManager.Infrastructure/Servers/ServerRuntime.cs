using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerRuntime : IServerRuntime
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerRuntime));

    private readonly IProcessRunner _processRunner;
    // 序列化 StartAsync 與 DisposeAsync，避免併發啟動兩個行程或啟動中途被處置
    private readonly SemaphoreSlim _stateGate = new(1, 1);

    // MonitorExitAsync 於背景執行緒將其設為 null，讀取端一律先取區域快照
    private volatile IManagedProcess? _process;
    private volatile bool _disposed;
    // 0 = 未就緒，1 = 已就緒；以 Interlocked 確保 ServerReady 僅觸發一次
    private int _isReady;
    private long _startedTimestamp;
    private int? _lastExitCode;
    private Task? _monitorTask;

    public ServerRuntime(IProcessRunner processRunner)
    {
        ArgumentNullException.ThrowIfNull(processRunner);
        _processRunner = processRunner;
    }

    public int Pid => _process?.Pid ?? 0;
    public bool IsRunning => _process is { HasExited: false };
    public bool HasExited => _lastExitCode is not null || _process is null or { HasExited: true };
    public bool IsReady => Volatile.Read(ref _isReady) != 0;
    public long? StartedTimestamp => Interlocked.Read(ref _startedTimestamp) is var ts and not 0 ? ts : null;
    public int? ExitCode => _process?.ExitCode ?? _lastExitCode;
    public long? GetWorkingSet64() => _process?.GetWorkingSet64();

    public event Action<string>? OutputLineReceived;
    public event Action<int>? ServerStarted;
    public event Action<int>? ServerExited;
    public event Action? ServerReady;

    public async Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(plan);
        await _stateGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await StartCoreAsync(plan, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _stateGate.Release();
        }
    }

    private async Task StartCoreAsync(ServerLaunchPlan plan, CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (IsRunning)
        {
            Logger.Warning("嘗試啟動伺服器但已有行程在執行中 (PID: {Pid})", Pid);
            throw new InvalidOperationException("伺服器行程已在執行中");
        }

        Interlocked.Exchange(ref _isReady, 0);
        _lastExitCode = null;
        string stableDir = SafeFileSystem.ResolveStableDirectory(plan.WorkingDirectory);

        if (plan.IsScript)
        {
            string fullScriptPath = ResolveScriptPath(stableDir, plan.JavaExecutable);

            if (!SafeFileSystem.IsPathWithin(stableDir, fullScriptPath, strict: false))
            {
                throw new SafeFileSystemException($"偵測到非法的啟動腳本路徑超出邊界：{plan.JavaExecutable}");
            }

            if (!SafeScriptValidator.ValidateScriptContent(fullScriptPath, stableDir))
            {
                throw new InvalidOperationException($"啟動腳本「{plan.JavaExecutable}」未通過安全性檢驗");
            }
        }

        Logger.Information("啟動伺服器行程 (目錄: {Directory}, Java: {Java}, 參數量: {ArgCount})", stableDir, plan.JavaExecutable, plan.Arguments.Count);

        var spec = new ProcessStartSpec(
            FileName: plan.JavaExecutable,
            Arguments: plan.Arguments,
            WorkingDirectory: stableDir,
            Environment: plan.Environment);

        var started = await _processRunner.StartAsync(
            spec,
            outputLineObserved: OnOutputLineObserved,
            cancellationToken: cancellationToken).ConfigureAwait(false);
        started.OutputReceived += OnOutputReceived;
        _process = started;
        Interlocked.Exchange(ref _startedTimestamp, System.Diagnostics.Stopwatch.GetTimestamp());
        string serverName = plan.ServerName ?? Path.GetFileName(stableDir);
        Logger.Information("伺服器「{Server}」行程已啟動，PID: {Pid}", serverName, started.Pid);
        ServerStarted?.Invoke(started.Pid);

        _monitorTask = MonitorExitAsync(started);
    }

    public async Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(command);

        var proc = _process;
        if (proc is not { HasExited: false })
        {
            Logger.Warning("傳送指令失敗，伺服器未在執行狀態");
            return false;
        }

        try
        {
            // 僅記錄指令名稱，不記錄參數（可能含玩家名稱等個資）
            var trimmed = command.AsSpan().TrimStart();
            int space = trimmed.IndexOf(' ');
            Logger.Information("傳送伺服器主控台指令: {Command}", (space < 0 ? trimmed : trimmed[..space]).ToString());
            await proc.WriteLineAsync(command, cancellationToken).ConfigureAwait(false);
            return true;
        }
        catch (OperationCanceledException)
        {
            // 呼叫端取消屬預期流程，不記為錯誤
            Logger.Information("傳送伺服器主控台指令已取消");
            throw;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "傳送指令至伺服器標準輸入失敗");
            return false;
        }
    }

    public async Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        var proc = _process;
        if (!IsRunning || proc is null)
        {
            return new ProcessExitResult(ExitCode ?? 0, false);
        }

        Logger.Information("傳送伺服器停止請求 (stop 指令，平順終止等候: {Timeout})", gracefulTimeout);

        // 嘗試寫入 stop 讓伺服器正常存檔關閉
        await SendCommandAsync("stop", cancellationToken).ConfigureAwait(false);

        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        linked.CancelAfter(gracefulTimeout);

        try
        {
            return await proc.WaitForExitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            Logger.Warning("伺服器未在 {Timeout} 內平順關閉，傳送強制終止命令", gracefulTimeout);
            // 逾時，強制樹狀終止
            return await proc.StopAsync(TimeSpan.Zero, cancellationToken).ConfigureAwait(false);
        }
    }

    public async Task<ProcessExitResult?> WaitForExitAsync(TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        var proc = _process;
        if (proc is null || proc.HasExited)
        {
            return new ProcessExitResult(ExitCode ?? 0, false);
        }

        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        linked.CancelAfter(timeout);

        try
        {
            return await proc.WaitForExitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            Logger.Information("等待伺服器行程結束逾時 ({Timeout})", timeout);
            return null;
        }
    }

    public async ValueTask DisposeAsync()
    {
        await _stateGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;

            var proc = _process;
            if (proc is not null)
            {
                Logger.Information("處置伺服器行程資源 (PID: {Pid})", proc.Pid);
                proc.OutputReceived -= OnOutputReceived;
                await proc.DisposeAsync().ConfigureAwait(false);
                if (proc.HasExited)
                {
                    _process = null;
                    Interlocked.Exchange(ref _startedTimestamp, 0);
                }
            }

            if (_monitorTask is { } monitorTask)
            {
                try
                {
                    await monitorTask.ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    Logger.Warning(ex, "等待伺服器監控任務完成時發生例外");
                }
            }

            Interlocked.Exchange(ref _isReady, 0);
        }
        finally
        {
            _stateGate.Release();
        }
    }

    private void OnOutputReceived(ProcessOutput output) => OutputLineReceived?.Invoke(output.Text);

    private void OnOutputLineObserved(ProcessOutput output)
    {
        if (_disposed)
        {
            return;
        }

        string text = output.Text;
        if (!IsReady
            && (text.Contains("Done (", StringComparison.OrdinalIgnoreCase) || text.Contains("Done in ", StringComparison.OrdinalIgnoreCase))
            && Interlocked.CompareExchange(ref _isReady, 1, 0) == 0)
        {
            Logger.Information("伺服器已進入就緒 (Ready) 狀態");
            ServerReady?.Invoke();
        }
    }

    private async Task MonitorExitAsync(IManagedProcess proc)
    {
        int exitCode;
        try
        {
            var result = await proc.WaitForExitAsync().ConfigureAwait(false);
            Logger.Information("伺服器監控回報行程 (PID: {Pid}) 已結束，結束代碼: {ExitCode}, 是否被強制終止: {WasForceStopped}", proc.Pid, result.ExitCode, result.WasForceStopped);
            exitCode = result.ExitCode;
        }
        catch (Exception ex)
        {
            // 背景監控無呼叫端可接收例外，記錄完整例外後仍以結束事件通知
            Logger.Error(ex, "伺服器行程監控失敗 (PID: {Pid})", proc.Pid);
            exitCode = proc.ExitCode ?? -1;
        }

        // 先清除狀態再觸發事件，訂閱者讀到的 IsRunning／IsReady 與事件一致
        proc.OutputReceived -= OnOutputReceived;
        _lastExitCode = exitCode;
        if (ReferenceEquals(_process, proc))
        {
            _process = null;
            Interlocked.Exchange(ref _startedTimestamp, 0);
        }

        Interlocked.Exchange(ref _isReady, 0);

        try
        {
            // 伺服器自行結束時在此釋放行程資源
            if (!_disposed)
            {
                await proc.DisposeAsync().ConfigureAwait(false);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "釋放已結束的伺服器行程資源失敗 (PID: {Pid})", proc.Pid);
        }

        ServerExited?.Invoke(exitCode);
    }
    private static string ResolveScriptPath(string stableDir, string scriptExecutable) =>
        Path.GetFullPath(scriptExecutable, stableDir);
}
