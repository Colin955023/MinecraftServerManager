namespace MinecraftServerManager.Core.Ports;

/// <summary>外部行程輸出串流來源</summary>
public enum ProcessOutputKind
{
    StandardOutput,
    StandardError,
}

/// <summary>外部行程單行輸出訊息</summary>
public sealed record ProcessOutput(ProcessOutputKind Kind, string Text);

/// <summary>外部行程啟動規格</summary>
public sealed record ProcessStartSpec(
    string FileName,
    IReadOnlyList<string> Arguments,
    string? WorkingDirectory = null,
    IReadOnlyDictionary<string, string?>? Environment = null,
    bool CreateNoWindow = true,
    bool UseShellExecute = false);

/// <summary>外部行程結束結果</summary>
public sealed record ProcessExitResult(int ExitCode, bool WasForceStopped);

/// <summary>受管理的執行中外部行程</summary>
public interface IManagedProcess : IAsyncDisposable
{
    public int Pid { get; }

    public bool HasExited { get; }

    public int? ExitCode { get; }

    /// <summary>子行程輸出逐行讀取時立即觸發，處理常式須快速完成；不受顯示佇列淘汰影響</summary>
    public event Action<ProcessOutput>? OutputLineObserved;

    public event Action<ProcessOutput>? OutputReceived;

    /// <summary>顯示派送佇列與未訂閱積壓佇列累計捨棄的輸出行數</summary>
    public long DroppedOutputLines { get; }

    public Task WriteLineAsync(string line, CancellationToken cancellationToken = default);

    public Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default);

    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default);

    /// <summary>行程工作集（位元組）；已結束或失敗回傳 null</summary>
    public long? GetWorkingSet64();
}

/// <summary>外部行程啟動器</summary>
public interface IProcessRunner
{
    /// <summary>啟動受管理行程並重導向標準輸入／輸出</summary>
    public Task<IManagedProcess> StartAsync(
        ProcessStartSpec specification,
        Action<ProcessOutput>? outputLineObserved = null,
        CancellationToken cancellationToken = default);

    /// <summary>啟動不受管理、不等待結束的行程（例如更新安裝程式）；呼叫端須先確認執行檔來源可信</summary>
    public void StartDetached(ProcessStartSpec specification);
}
