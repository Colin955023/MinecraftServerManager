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

    /// <summary>
    /// 取得目前行程之工作集（實體記憶體用量，位元組），若行程已結束或查詢失敗則傳回 null。
    /// </summary>
    public long? GetWorkingSet64();
}

public interface IProcessRunner
{
    public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default);

    public void StartDetached(ProcessStartSpec specification) =>
        throw new NotSupportedException("此行程執行器不支援啟動脫離管理的行程");
}

public interface IExternalLauncher
{
    public bool OpenFolder(string folderPath, bool isTrusted = false);

    public bool ShowInFolder(string filePath, bool isTrusted = false);

    public bool OpenFile(string filePath, bool isTrusted = false);

    public bool OpenUrl(string url, bool isTrusted = false);
}
