using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>單一伺服器之行程執行與生命週期控制抽象介面（每台伺服器各自一個，由 <see cref="IServerRuntimeHost"/> 管理）</summary>
public interface IServerRuntime : IAsyncDisposable
{
    public int Pid { get; }
    public bool IsRunning { get; }
    public bool IsReady { get; }
    /// <summary>最近一次行程結束代碼；尚未結束過或重新啟動後為 null</summary>
    public int? ExitCode { get; }

    /// <summary>取得伺服器行程目前之工作集（實體記憶體用量，位元組），若未執行或查詢失敗則傳回 null。</summary>
    public long? GetWorkingSet64();

    public event Action<string>? OutputLineReceived;
    public event Action? ServerStarted;
    public event Action<int>? ServerExited;
    public event Action? ServerReady;

    /// <summary>依據強型別啟動計畫啟動伺服器行程</summary>
    public Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default);

    /// <summary>寫入主控台指令</summary>
    public Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default);

    /// <summary>平順停止伺服器（傳送 stop 指令），逾時則強制樹狀終止</summary>
    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default);

    /// <summary>等待行程結束但不強制終止；於時限內結束回傳結果，逾時回傳 null，未執行時立即回傳最近一次結果</summary>
    public Task<ProcessExitResult?> WaitForExitAsync(TimeSpan timeout, CancellationToken cancellationToken = default);
}
