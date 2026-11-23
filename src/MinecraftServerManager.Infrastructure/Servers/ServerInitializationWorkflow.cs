using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器初次啟動初始化流程：啟動、偵測就緒後平順停止</summary>
public sealed class ServerInitializationWorkflow : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerInitializationWorkflow));
    private static readonly TimeSpan ReadyStopTimeout = TimeSpan.FromSeconds(30);

    private readonly IServerRuntime _runtime;
    private readonly IServerLaunchPlanner _launchPlanner;
    private readonly CancellationTokenSource _cts = new();
    private volatile bool _readyDetected;
    private volatile bool _disposed;
    private int _stopAfterReadyRequested;

    public ServerInitializationWorkflow(IServerRuntime runtime, IServerLaunchPlanner launchPlanner)
    {
        ArgumentNullException.ThrowIfNull(runtime);
        ArgumentNullException.ThrowIfNull(launchPlanner);
        _runtime = runtime;
        _launchPlanner = launchPlanner;
        _runtime.ServerReady += OnServerReady;
    }

    public bool ReadyDetected => _readyDetected;

    /// <summary>於背景解析啟動檔：優先啟動腳本，否則依載入器解析啟動目標</summary>
    public Task<string> ResolveExecutableNameAsync(string serverPath, LoaderKind loader)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return Task.Run(() => ResolveExecutableName(serverPath, loader));
    }

    private static string ResolveExecutableName(string serverPath, LoaderKind loader)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return ServerDefaults.ServerJarFileName;
        }

        return SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.StartServerBatFileName))
            ? ServerDefaults.StartServerBatFileName
            : ServerLaunchTargetResolver.ResolveLaunchTarget(serverPath, loader);
    }

    public async Task StartAsync(string javaExecutablePath, ServerConfig config, string executableName)
    {
        ArgumentNullException.ThrowIfNull(config);
        var plan = await Task.Run(() => _launchPlanner.CreatePlan(config, executableName, javaExecutablePath)).ConfigureAwait(false);
        await _runtime.StartAsync(plan).ConfigureAwait(false);
    }

    /// <summary>平順停止伺服器；伺服器未執行時不做任何事</summary>
    public async Task StopAsync(TimeSpan gracefulTimeout)
    {
        if (!_runtime.IsRunning)
        {
            return;
        }

        await _runtime.StopAsync(gracefulTimeout).ConfigureAwait(false);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _runtime.ServerReady -= OnServerReady;
        _cts.Cancel();
        _cts.Dispose();
    }

    private void OnServerReady()
    {
        _readyDetected = true;

        // 處置後或已送出停止要求時不再重複停止
        if (_disposed || Interlocked.Exchange(ref _stopAfterReadyRequested, 1) != 0)
        {
            return;
        }

        _ = StopAfterReadyAsync(_cts.Token);
    }

    private async Task StopAfterReadyAsync(CancellationToken cancellationToken)
    {
        try
        {
            await _runtime.StopAsync(ReadyStopTimeout, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器初始化流程已處置，取消等待停止");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "傳送 stop 指令或終止行程時發生例外");
        }
    }
}
