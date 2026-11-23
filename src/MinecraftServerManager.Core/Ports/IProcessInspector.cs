namespace MinecraftServerManager.Core.Ports;

/// <summary>既有行程查詢與終止抽象介面（供遺留伺服器行程偵測使用）</summary>
public interface IProcessInspector
{
    /// <summary>行程啟動時間（UTC 位移）；無法查詢回傳 null</summary>
    public DateTimeOffset? GetStartTimeUtc(int pid);

    /// <summary>強制終止指定 PID 的行程及其子行程；行程已不存在視為成功</summary>
    public bool KillProcessTree(int pid);
}
