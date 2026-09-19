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
    IReadOnlyDictionary<string, string?>? Environment = null);

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
}

public interface IProcessRunner
{
    public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default);
}

public interface IExternalLauncher
{
    public bool OpenFolder(string folderPath);

    public bool OpenUrl(string url);
}
