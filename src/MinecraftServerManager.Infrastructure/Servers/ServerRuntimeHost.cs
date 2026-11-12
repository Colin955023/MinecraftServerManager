using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>多伺服器執行階段管理：每台伺服器各自持有一個 <see cref="ServerRuntime"/>，並同步行程登記</summary>
public sealed class ServerRuntimeHost(IProcessRunner processRunner, IRunningServerRegistry registry) : IServerRuntimeHost
{
    private readonly Dictionary<string, ServerRuntime> _runtimes = new(StringComparer.OrdinalIgnoreCase);
    private readonly Lock _lock = new();

    public event Action<string>? ServerStateChanged;

    public bool IsAnyRunning
    {
        get
        {
            lock (_lock)
            {
                return _runtimes.Values.Any(static r => r.IsRunning);
            }
        }
    }

    public IServerRuntime GetRuntime(string serverName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);

        lock (_lock)
        {
            if (_runtimes.TryGetValue(serverName, out var existing))
            {
                return existing;
            }

            var runtime = new ServerRuntime(processRunner);
            runtime.ServerStarted += () =>
            {
                registry.Record(serverName, runtime.Pid);
                ServerStateChanged?.Invoke(serverName);
            };
            runtime.ServerReady += () => ServerStateChanged?.Invoke(serverName);
            runtime.ServerExited += _ =>
            {
                registry.Remove(serverName);
                ServerStateChanged?.Invoke(serverName);
            };
            _runtimes[serverName] = runtime;
            return runtime;
        }
    }

    public bool IsRunning(string serverName)
    {
        lock (_lock)
        {
            return _runtimes.TryGetValue(serverName, out var runtime) && runtime.IsRunning;
        }
    }

    public IReadOnlyList<string> GetRunningServerNames()
    {
        lock (_lock)
        {
            return [.. _runtimes.Where(static p => p.Value.IsRunning).Select(static p => p.Key)];
        }
    }

    public async ValueTask DisposeAsync()
    {
        ServerRuntime[] runtimes;
        lock (_lock)
        {
            runtimes = [.. _runtimes.Values];
            _runtimes.Clear();
        }

        foreach (var runtime in runtimes)
        {
            await runtime.DisposeAsync().ConfigureAwait(false);
        }
    }
}
