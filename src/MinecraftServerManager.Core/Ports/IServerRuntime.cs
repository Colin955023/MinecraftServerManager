using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器行程執行與生命週期控制抽象介面
/// </summary>
public interface IServerRuntime : IAsyncDisposable
{
    public int Pid { get; }
    public bool IsRunning { get; }
    public bool IsReady { get; }
    public int? ExitCode { get; }
    public string? ActiveServerName { get; }

    /// <summary>
    /// 取得伺服器行程目前之工作集（實體記憶體用量，位元組），若未執行或查詢失敗則傳回 null。
    /// </summary>
    public long? GetWorkingSet64();

    public event Action<string>? OutputLineReceived;
    public event Action? ServerStarted;
    public event Action<int>? ServerExited;
    public event Action? ServerReady;

    /// <summary>
    /// 依據強型別啟動計畫啟動伺服器行程
    /// </summary>
    public Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default);

    /// <summary>
    /// 啟動伺服器行程
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
    /// 平順停止伺服器（傳送 stop 指令），逾時則強制樹狀終止
    /// </summary>
    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default);
}
