using MinecraftServerManager.Domain.Servers;
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
    public bool IsReady { get; private set; }
    public int? ExitCode => _process?.ExitCode;
    public string? ActiveServerName { get; private set; }
    public long? GetWorkingSet64() => _process?.GetWorkingSet64();

    public event Action<string>? OutputLineReceived;
    public event Action? ServerStarted;
    public event Action<int>? ServerExited;
    public event Action? ServerReady;

    public async Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(plan);

        if (IsRunning)
        {
            Logger.Warning("嘗試啟動伺服器但已有行程在執行中 (PID: {Pid})", Pid);
            throw new InvalidOperationException("伺服器行程已在執行中");
        }

        IsReady = false;
        string stableDir = SafeFileSystem.ResolveStableDirectory(plan.WorkingDirectory);

        if (plan.IsScript)
        {
            string scriptPath = Path.IsPathRooted(plan.JavaExecutable)
                ? plan.JavaExecutable
                : Path.Combine(stableDir, plan.JavaExecutable);
            string fullScriptPath = Path.GetFullPath(scriptPath);

            if (!SafeFileSystem.IsPathWithin(stableDir, fullScriptPath, strict: false))
            {
                throw new SafeFileSystemException($"偵測到非法的啟動腳本路徑越界：{plan.JavaExecutable}");
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

        _process = await processRunner.StartAsync(spec, cancellationToken).ConfigureAwait(false);
        ActiveServerName = plan.ServerName ?? Path.GetFileName(stableDir);
        Logger.Information("伺服器「{Server}」行程已啟動，PID: {Pid}", ActiveServerName, _process.Pid);
        _process.OutputReceived += OnOutputReceived;
        ServerStarted?.Invoke();

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

        string stableDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        bool isScript = executableName.EndsWith(".bat", StringComparison.OrdinalIgnoreCase);

        ServerLaunchPlan plan;
        if (isScript)
        {
            string scriptPath = Path.IsPathRooted(executableName)
                ? executableName
                : Path.Combine(stableDir, executableName);
            string fullScriptPath = Path.GetFullPath(scriptPath);

            IReadOnlyDictionary<string, string?>? env = null;
            if (!string.IsNullOrWhiteSpace(javaExecutablePath) && !string.Equals(javaExecutablePath.Trim(), "java", StringComparison.OrdinalIgnoreCase))
            {
                env = ServerLaunchPlanner.BuildJavaEnvironment(javaExecutablePath.Trim());
            }

            plan = new ServerLaunchPlan(
                JavaExecutable: fullScriptPath,
                WorkingDirectory: stableDir,
                Arguments: [],
                Loader: LoaderKind.Unknown,
                MinMemoryMb: memoryMinMb ?? 1024,
                MaxMemoryMb: memoryMaxMb,
                IsScript: true,
                ServerName: Path.GetFileName(stableDir),
                Environment: env);
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

            plan = new ServerLaunchPlan(
                JavaExecutable: javaExecutablePath,
                WorkingDirectory: stableDir,
                Arguments: args,
                Loader: LoaderKind.Unknown,
                MinMemoryMb: min,
                MaxMemoryMb: memoryMaxMb,
                IsScript: false,
                ServerName: Path.GetFileName(stableDir));
        }

        await StartAsync(plan, cancellationToken).ConfigureAwait(false);
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

        var proc = _process;
        if (!IsRunning || proc is null)
        {
            return new ProcessExitResult(ExitCode ?? 0, false);
        }

        Logger.Information("傳送伺服器停止請求 (stop 指令，平順終止等候: {Timeout})", gracefulTimeout);

        // 嘗試寫入 stop 讓伺服器正常存檔關閉
        await SendCommandAsync("stop", cancellationToken).ConfigureAwait(false);

        using var timeoutCts = new CancellationTokenSource(gracefulTimeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);

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

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        ActiveServerName = null;

        if (_process is not null)
        {
            Logger.Information("處置伺服器行程資源 (PID: {Pid})", _process.Pid);
            _process.OutputReceived -= OnOutputReceived;
            await _process.DisposeAsync().ConfigureAwait(false);
            _process = null;
        }
        IsReady = false;
    }

    private void OnOutputReceived(ProcessOutput output)
    {
        string text = output.Text;
        OutputLineReceived?.Invoke(text);

        if (!IsReady && (text.Contains("Done (", StringComparison.OrdinalIgnoreCase) || text.Contains("Done in ", StringComparison.OrdinalIgnoreCase)))
        {
            IsReady = true;
            Logger.Information("伺服器已進入就緒 (Ready) 狀態");
            ServerReady?.Invoke();
        }
    }

    private async Task MonitorExitAsync(IManagedProcess proc)
    {
        try
        {
            var result = await proc.WaitForExitAsync().ConfigureAwait(false);
            Logger.Information("伺服器監控回報行程 (PID: {Pid}) 已結束，結束代碼: {ExitCode}, 是否被強制終止: {WasForceStopped}", proc.Pid, result.ExitCode, result.WasForceStopped);
            IsReady = false;
            ServerExited?.Invoke(result.ExitCode);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "伺服器行程監控異常 (PID: {Pid})", proc.Pid);
        }
        finally
        {
            proc.OutputReceived -= OnOutputReceived;
            if (ReferenceEquals(_process, proc))
            {
                _process = null;
            }
            ActiveServerName = null;
            IsReady = false;
        }
    }
}
