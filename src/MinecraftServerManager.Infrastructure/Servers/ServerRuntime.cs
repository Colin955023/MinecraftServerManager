using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerRuntime(IProcessRunner processRunner) : IServerRuntime
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerRuntime");

    private IManagedProcess? _process;
    private bool _disposed;

    public int Pid => _process?.Pid ?? 0;
    public bool IsRunning => _process is not null && !_process.HasExited;
    public int? ExitCode => _process?.ExitCode;

    public event Action<string>? OutputLineReceived;
    public event Action<int>? ServerExited;

    public async Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(plan);

        if (IsRunning)
        {
            Logger.Warning("嘗試啟動伺服器但已有程序在執行中 (PID: {Pid})", Pid);
            throw new InvalidOperationException("伺服器程序已在執行中");
        }

        string stableDir = SafeFileSystem.ResolveStableDirectory(plan.WorkingDirectory);
        Logger.Information("啟動伺服器程序 (目錄: {Directory}, Java: {Java}, 參數量: {ArgCount})", stableDir, plan.JavaExecutable, plan.Arguments.Count);

        var spec = new ProcessStartSpec(
            FileName: plan.JavaExecutable,
            Arguments: plan.Arguments,
            WorkingDirectory: stableDir);

        _process = await processRunner.StartAsync(spec, cancellationToken).ConfigureAwait(false);
        Logger.Information("伺服器程序已啟動，PID: {Pid}", _process.Pid);
        _process.OutputReceived += OnOutputReceived;

        _ = MonitorExitAsync(_process);
    }

    public async Task StartAsync(
        string javaExecutablePath,
        string serverDirectory,
        string executableName,
        int memoryMaxMb,
        int? memoryMinMb = null,
        IReadOnlyList<string>? customJvmArgs = null,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(executableName);

        if (IsRunning)
        {
            Logger.Warning("嘗試啟動伺服器但已有程序在執行中 (PID: {Pid})", Pid);
            throw new InvalidOperationException("伺服器程序已在執行中");
        }

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        bool isScript = executableName.EndsWith(".bat", StringComparison.OrdinalIgnoreCase);

        ProcessStartSpec spec;
        if (isScript)
        {
            string scriptPath = Path.Combine(stableDir, executableName);
            Logger.Information("啟動批次檔腳本伺服器 (路徑: {Script})", scriptPath);
            spec = new ProcessStartSpec(
                FileName: scriptPath,
                Arguments: [],
                WorkingDirectory: stableDir);
        }
        else
        {
            var args = new List<string>();
            int min = memoryMinMb ?? (memoryMaxMb > 1024 ? 1024 : memoryMaxMb);
            args.Add($"-Xms{min}M");
            args.Add($"-Xmx{memoryMaxMb}M");

            if (customJvmArgs is not null)
            {
                args.AddRange(customJvmArgs);
            }

            args.Add("-jar");
            args.Add(executableName);
            args.Add("nogui");

            Logger.Information("啟動 Java 伺服器 (目錄: {Directory}, Jar: {Jar}, 記憶體: {Min}M-{Max}M)", stableDir, executableName, min, memoryMaxMb);
            spec = new ProcessStartSpec(
                FileName: javaExecutablePath,
                Arguments: args,
                WorkingDirectory: stableDir);
        }

        _process = await processRunner.StartAsync(spec, cancellationToken).ConfigureAwait(false);
        Logger.Information("伺服器程序已成功啟動，PID: {Pid}", _process.Pid);
        _process.OutputReceived += OnOutputReceived;

        _ = MonitorExitAsync(_process);
    }

    public async Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(command);

        if (!IsRunning || _process is null)
        {
            Logger.Warning("傳送指令失敗，伺服器未在執行狀態");
            return false;
        }

        try
        {
            Logger.Information("傳送伺服器控制台指令: {Command}", command);
            await _process.WriteLineAsync(command, cancellationToken).ConfigureAwait(false);
            return true;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "傳送指令至伺服器標準輸入失敗: {Message}", ex.Message);
            return false;
        }
    }

    public async Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (!IsRunning || _process is null)
        {
            return new ProcessExitResult(ExitCode ?? 0, false);
        }

        Logger.Information("發送伺服器停止請求 (stop 指令，優雅終止等候: {Timeout})", gracefulTimeout);

        // 嘗試寫入 stop 讓伺服器正常存檔關閉
        await SendCommandAsync("stop", cancellationToken).ConfigureAwait(false);

        using var timeoutCts = new CancellationTokenSource(gracefulTimeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);

        try
        {
            return await _process.WaitForExitAsync(linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            Logger.Warning("伺服器未在 {Timeout} 內優雅關閉，發送強制終止命令", gracefulTimeout);
            // 逾時，強制樹狀終止
            return await _process.StopAsync(TimeSpan.Zero, cancellationToken).ConfigureAwait(false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;

        if (_process is not null)
        {
            Logger.Information("處置伺服器程序資源 (PID: {Pid})", _process.Pid);
            await _process.DisposeAsync().ConfigureAwait(false);
            _process = null;
        }
    }

    private void OnOutputReceived(ProcessOutput output) => OutputLineReceived?.Invoke(output.Text);

    private async Task MonitorExitAsync(IManagedProcess proc)
    {
        try
        {
            var result = await proc.WaitForExitAsync().ConfigureAwait(false);
            Logger.Information("伺服器監控回報程序 (PID: {Pid}) 已結束，結束代碼: {ExitCode}, 是否被強制終止: {WasForceStopped}", proc.Pid, result.ExitCode, result.WasForceStopped);
            ServerExited?.Invoke(result.ExitCode);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "伺服器程序監控異常 (PID: {Pid})", proc.Pid);
        }
    }
}
