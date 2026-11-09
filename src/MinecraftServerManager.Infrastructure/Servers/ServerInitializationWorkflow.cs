using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器初次啟動初始化流程：解析啟動目標、啟動行程，偵測到就緒訊號後平順停止，並記錄是否已完成初始化。
/// UI 僅負責顯示，流程判斷皆於此處完成。
/// </summary>
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

    /// <summary>
    /// 是否已偵測到伺服器就緒訊號（初始化已完成）
    /// </summary>
    public bool ReadyDetected => _readyDetected;

    /// <summary>
    /// 解析初次啟動所用的啟動檔：存在啟動腳本時優先使用，否則使用 server.jar
    /// </summary>
    public static string ResolveExecutableName(string serverPath) =>
        !string.IsNullOrWhiteSpace(serverPath) && SafeFileSystem.FileExists(Path.Combine(serverPath, ServerDefaults.StartServerBatFileName))
            ? ServerDefaults.StartServerBatFileName
            : "server.jar";

    /// <summary>
    /// 以指定的啟動檔案啟動伺服器行程（經啟動規劃器套用安全檢驗、GC 與 nogui 參數）
    /// </summary>
    public async Task StartAsync(string javaExecutablePath, ServerConfig config, string executableName)
    {
        ArgumentNullException.ThrowIfNull(config);
        var plan = await Task.Run(() => _launchPlanner.CreatePlan(config, executableName, javaExecutablePath)).ConfigureAwait(false);
        await _runtime.StartAsync(plan).ConfigureAwait(false);
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
