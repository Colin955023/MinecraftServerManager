namespace MinecraftServerManager.Core.Ports;

/// <summary>已記錄的伺服器行程：啟動時間用於辨識 PID 是否已被其他行程重用</summary>
public sealed record TrackedServerProcess(string ServerName, int Pid, long StartTimeUtcTicks);

/// <summary>執行中伺服器行程登記抽象介面，供程式異常結束後偵測遺留行程</summary>
public interface IRunningServerRegistry
{
    /// <summary>登記伺服器行程已啟動（不阻塞呼叫端）</summary>
    public void Record(string serverName, int pid);

    /// <summary>移除伺服器行程登記（不阻塞呼叫端）</summary>
    public void Remove(string serverName);

    /// <summary>找出上次執行所遺留且仍存活的伺服器行程，並清除已不存在者的登記</summary>
    public Task<IReadOnlyList<TrackedServerProcess>> FindOrphansAsync(CancellationToken cancellationToken = default);

    /// <summary>強制終止遺留行程（含子行程）並移除登記；行程已不存在或終止成功回傳 true</summary>
    public Task<bool> TerminateAsync(TrackedServerProcess process, CancellationToken cancellationToken = default);
}
