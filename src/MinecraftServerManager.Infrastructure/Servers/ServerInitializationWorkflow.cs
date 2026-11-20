using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
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
    private volatile bool _readyDetected;
    private bool _disposed;

    public ServerInitializationWorkflow(IServerRuntime runtime, IServerLaunchPlanner launchPlanner)
    {
        ArgumentNullException.ThrowIfNull(runtime);
        ArgumentNullException.ThrowIfNull(launchPlanner);
        _runtime = runtime;
        _launchPlanner = launchPlanner;
        _runtime.ServerReady += OnServerReady;
    }

    public bool ReadyDetected => _readyDetected;

    /// <summary>解析啟動檔：優先啟動腳本，否則 server.jar</summary>
    public static string ResolveExecutableName(string serverPath) =>
        !string.IsNullOrWhiteSpace(serverPath) && SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.StartServerBatFileName))
            ? ServerDefaults.StartServerBatFileName
            : "server.jar";

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
    }

    private void OnServerReady()
    {
        _readyDetected = true;
        _ = StopAfterReadyAsync();
    }

    private async Task StopAfterReadyAsync()
    {
        try
        {
            await _runtime.StopAsync(ReadyStopTimeout).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "傳送 stop 指令或終止行程時發生例外");
        }
    }
}
