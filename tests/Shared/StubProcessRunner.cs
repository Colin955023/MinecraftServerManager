using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.TestSupport;

/// <summary>測試用共用行程啟動器替身：支援自訂建立函式、預設結束代碼、執行回呼與啟動失敗模擬</summary>
internal sealed class StubProcessRunner : IProcessRunner
{
    private readonly Func<ProcessStartSpec, IManagedProcess> _factory;

    public ProcessStartSpec? LastSpecification { get; private set; }
    public StubManagedProcess? LastCreatedProcess { get; private set; }

    public StubProcessRunner(
        int exitCode = 0,
        Action<ProcessStartSpec>? onStart = null,
        bool shouldFailStart = false,
        bool interactive = false)
    {
        _factory = spec =>
        {
            if (shouldFailStart)
            {
                throw new FileNotFoundException("找不到指定執行檔");
            }

            onStart?.Invoke(spec);
            var proc = new StubManagedProcess(exitCode, interactive);
            LastCreatedProcess = proc;
            return proc;
        };
    }

    public StubProcessRunner(Func<ProcessStartSpec, StubManagedProcess> factory)
    {
        ArgumentNullException.ThrowIfNull(factory);
        _factory = spec =>
        {
            var proc = factory(spec);
            LastCreatedProcess = proc;
            return proc;
        };
    }

    public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default)
    {
        LastSpecification = specification;
        return Task.FromResult(_factory(specification));
    }
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

    public event Action<ProcessOutput>? OutputReceived;

    public StubManagedProcess(int exitCode = 0, bool interactive = false, IEnumerable<ProcessOutput>? initialOutputs = null)
    {
        _defaultExitCode = exitCode;
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

    private readonly List<ProcessOutput>? _initialOutputs;

    public void RaiseOutput(string line, ProcessOutputKind kind = ProcessOutputKind.StandardOutput) =>
        OutputReceived?.Invoke(new ProcessOutput(kind, line));

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
        return ValueTask.CompletedTask;
    }

    public long? GetWorkingSet64() => null;
}
