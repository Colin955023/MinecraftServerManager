using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器進程執行與生命週期控制抽象介面
/// </summary>
public interface IServerRuntime : IAsyncDisposable
{
    public int Pid { get; }
    public bool IsRunning { get; }
    public int? ExitCode { get; }

    public event Action<string>? OutputLineReceived;
    public event Action<int>? ServerExited;

    /// <summary>
    /// 依據強型別啟動計畫啟動伺服器程序
    /// </summary>
    public Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default);

    /// <summary>
    /// 啟動伺服器程序
    /// </summary>
    public Task StartAsync(
        string javaExecutablePath,
        string serverDirectory,
        string executableName,
        int memoryMaxMb,
        int? memoryMinMb = null,
        IReadOnlyList<string>? customJvmArgs = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 寫入控制台指令
    /// </summary>
    public Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default);

    /// <summary>
    /// 優雅停止伺服器（發送 stop 命令），逾時則強制樹狀終止
    /// </summary>
    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default);
}
