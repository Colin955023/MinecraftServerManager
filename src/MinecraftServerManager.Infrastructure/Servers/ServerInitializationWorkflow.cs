using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器初次啟動初始化流程：解析啟動目標、啟動行程，偵測到就緒訊號後平順停止，並記錄是否已完成初始化。
/// UI 僅負責顯示，流程判斷皆於此處完成。
/// </summary>
public sealed class ServerInitializationWorkflow : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerInitializationWorkflow");
    private static readonly TimeSpan ReadyStopTimeout = TimeSpan.FromSeconds(30);

    private readonly IServerRuntime _runtime;
    private volatile bool _readyDetected;
    private bool _disposed;

    public ServerInitializationWorkflow(IServerRuntime runtime)
    {
        _runtime = runtime ?? throw new ArgumentNullException(nameof(runtime));
        _runtime.ServerReady += OnServerReady;
    }

    /// <summary>
    /// 是否已偵測到伺服器就緒訊號（初始化已完成）
    /// </summary>
    public bool ReadyDetected => _readyDetected;

    /// <summary>
    /// 於背景解析伺服器目錄中初次啟動應執行的檔案名稱
    /// </summary>
    public static Task<string> ResolveStartupTargetAsync(ServerConfig config)
    {
        ArgumentNullException.ThrowIfNull(config);
        return Task.Run(() => ServerStartupTargetResolver.Resolve(config.Path));
    }

    /// <summary>
    /// 以指定的啟動檔案啟動伺服器行程
    /// </summary>
    public Task StartAsync(string javaExecutablePath, ServerConfig config, string executableName)
    {
        ArgumentNullException.ThrowIfNull(config);
        return _runtime.StartAsync(
            javaExecutablePath: javaExecutablePath,
            serverDirectory: config.Path,
            executableName: executableName,
            memoryMaxMb: config.MemoryMaxMb,
            memoryMinMb: config.MemoryMinMb,
            customJvmArgs: config.JvmArgs);
    }

    /// <summary>
    /// 平順停止伺服器；伺服器未執行時不做任何事
    /// </summary>
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
            Logger.Warning("傳送 stop 指令或終止行程時發生異常: {Message}", ex.Message);
        }
    }
}
