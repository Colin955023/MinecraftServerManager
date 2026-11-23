using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.TestSupport;

internal sealed class StubProcessRunner : IProcessRunner
{
    private readonly Func<ProcessStartSpec, Action<ProcessOutput>?, IManagedProcess> _factory;

    public ProcessStartSpec? LastSpecification { get; private set; }
    public StubManagedProcess? LastCreatedProcess { get; private set; }

    public StubProcessRunner(
        int exitCode = 0,
        Action<ProcessStartSpec>? onStart = null,
        bool shouldFailStart = false,
        bool interactive = false)
    {
        _factory = (spec, outputLineObserved) =>
        {
            if (shouldFailStart)
            {
                throw new FileNotFoundException("找不到指定執行檔");
            }

            onStart?.Invoke(spec);
            var proc = new StubManagedProcess(exitCode, interactive, outputLineObserved: outputLineObserved);
            LastCreatedProcess = proc;
            return proc;
        };
    }

    public StubProcessRunner(Func<ProcessStartSpec, StubManagedProcess> factory)
    {
        ArgumentNullException.ThrowIfNull(factory);
        _factory = (spec, outputLineObserved) =>
        {
            var proc = factory(spec);
            proc.AddOutputLineObserver(outputLineObserved);
            LastCreatedProcess = proc;
            return proc;
        };
    }

    public Task<IManagedProcess> StartAsync(
        ProcessStartSpec specification,
        Action<ProcessOutput>? outputLineObserved = null,
        CancellationToken cancellationToken = default)
    {
        // 與正式 ProcessRunner 一致：已取消即不啟動
        if (cancellationToken.IsCancellationRequested)
        {
            return Task.FromCanceled<IManagedProcess>(cancellationToken);
        }

        LastSpecification = specification;
        return Task.FromResult(_factory(specification, outputLineObserved));
    }

    public void StartDetached(ProcessStartSpec specification) =>
        // 測試不啟動獨立行程；呼叫端的啟動行為由其他測試驗證
        _ = specification;
}

/// <summary>測試用受控外部行程替身：支援立即完成模式與互動式等待模式</summary>
internal sealed class StubManagedProcess : IManagedProcess
{
    private readonly TaskCompletionSource<ProcessExitResult> _exitTcs = new();
    private readonly int _defaultExitCode;

    public int Pid => 1234;
    public bool HasExited { get; private set; }
    public int? ExitCode => HasExited ? _defaultExitCode : null;
    public List<string> WrittenLines { get; } = [];

    public Task Disposed => _disposedTcs.Task;

    private readonly TaskCompletionSource _disposedTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public event Action<ProcessOutput>? OutputReceived;
    public event Action<ProcessOutput>? OutputLineObserved;
    public long DroppedOutputLines { get; private set; }

    public StubManagedProcess(
        int exitCode = 0,
        bool interactive = false,
        IEnumerable<ProcessOutput>? initialOutputs = null,
        Action<ProcessOutput>? outputLineObserved = null)
    {
        _defaultExitCode = exitCode;
        OutputLineObserved += outputLineObserved;
        if (!interactive)
        {
            HasExited = true;
            _exitTcs.TrySetResult(new ProcessExitResult(exitCode, false));
        }

        if (initialOutputs is not null)
        {
            _initialOutputs = [.. initialOutputs];
        }
    }

    public void AddOutputLineObserver(Action<ProcessOutput>? observer) => OutputLineObserved += observer;

    private readonly List<ProcessOutput>? _initialOutputs;

    public void RaiseOutput(string line, ProcessOutputKind kind = ProcessOutputKind.StandardOutput)
    {
        var output = new ProcessOutput(kind, line);
        OutputLineObserved?.Invoke(output);
        OutputReceived?.Invoke(output);
    }

    public Task WriteLineAsync(string line, CancellationToken cancellationToken = default)
    {
        WrittenLines.Add(line);
        if (line == "stop")
        {
            HasExited = true;
            _exitTcs.TrySetResult(new ProcessExitResult(0, false));
        }

        return Task.CompletedTask;
    }

    public async Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default)
    {
        if (_initialOutputs is not null)
        {
            foreach (var output in _initialOutputs)
            {
                OutputLineObserved?.Invoke(output);
                OutputReceived?.Invoke(output);
            }
        }

        return await _exitTcs.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
    }

    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
    {
        HasExited = true;
        var res = new ProcessExitResult(-1, true);
        _exitTcs.TrySetResult(res);
        return Task.FromResult(res);
    }

    public ValueTask DisposeAsync()
    {
        HasExited = true;
        _exitTcs.TrySetResult(new ProcessExitResult(_defaultExitCode, true));
        _disposedTcs.TrySetResult();
        return ValueTask.CompletedTask;
    }

    public long? GetWorkingSet64() => null;
}
