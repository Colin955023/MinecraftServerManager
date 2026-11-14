namespace MinecraftServerManager.Core.Ports;

public enum ProcessOutputKind
{
    StandardOutput,
    StandardError,
}

public sealed record ProcessOutput(ProcessOutputKind Kind, string Text);

public sealed record ProcessStartSpec(
    string FileName,
    IReadOnlyList<string> Arguments,
    string? WorkingDirectory = null,
    IReadOnlyDictionary<string, string?>? Environment = null,
    bool CreateNoWindow = true,
    bool UseShellExecute = false);

public sealed record ProcessExitResult(int ExitCode, bool WasForceStopped);

public interface IManagedProcess : IAsyncDisposable
{
    public int Pid { get; }

    public bool HasExited { get; }

    public int? ExitCode { get; }

    public event Action<ProcessOutput>? OutputReceived;

    public Task WriteLineAsync(string line, CancellationToken cancellationToken = default);

    public Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default);

    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default);

    /// <summary>行程工作集（位元組）；已結束或失敗回傳 null</summary>
    public long? GetWorkingSet64();
}

public interface IProcessRunner
{
    public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default);

    public void StartDetached(ProcessStartSpec specification) =>
        throw new NotSupportedException("此行程執行器不支援啟動脫離管理的行程");
}

/// <summary>既有行程查詢與終止抽象介面（供遺留伺服器行程偵測使用）</summary>
public interface IProcessInspector
{
    /// <summary>行程啟動時間（UTC）；無法查詢回傳 null</summary>
    public DateTime? GetStartTimeUtc(int pid);

    /// <summary>強制終止指定 PID 的行程及其子行程；行程已不存在視為成功</summary>
    public bool KillProcessTree(int pid);
}

public interface IExternalLauncher
{
    public bool OpenFolder(string folderPath);

    public bool ShowInFolder(string filePath);

    public bool OpenFile(string filePath, bool isTrusted = false);

    public bool OpenUrl(string url, bool isTrusted = false);
}
