using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed class ServerRuntimeHost : IServerRuntimeHost
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerRuntimeHost));

    private readonly IProcessRunner _processRunner;
    private readonly IRunningServerRegistry _registry;
    private readonly Dictionary<string, ServerRuntime> _runtimes = new(StringComparer.OrdinalIgnoreCase);
    private readonly Lock _lock = new();

    public ServerRuntimeHost(IProcessRunner processRunner, IRunningServerRegistry registry)
    {
        ArgumentNullException.ThrowIfNull(processRunner);
        ArgumentNullException.ThrowIfNull(registry);
        _processRunner = processRunner;
        _registry = registry;
    }

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

            var runtime = new ServerRuntime(_processRunner);
            runtime.ServerStarted += pid =>
            {
                // 事件攜帶啟動當下的 PID，避免行程已結束時讀到 0
                if (pid > 0)
                {
                    _registry.Record(serverName, pid);
                }

                ServerStateChanged?.Invoke(serverName);
            };
            runtime.ServerReady += () => ServerStateChanged?.Invoke(serverName);
            runtime.ServerExited += _ =>
            {
                _registry.Remove(serverName);
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

    public async ValueTask<bool> ReleaseIdleRuntimeAsync(string serverName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);

        ServerRuntime? runtime;
        lock (_lock)
        {
            if (!_runtimes.TryGetValue(serverName, out runtime) || runtime.IsRunning)
            {
                return false;
            }

            _runtimes.Remove(serverName);
        }

        await runtime.DisposeAsync().ConfigureAwait(false);
        return true;
    }

    public async ValueTask DisposeAsync()
    {
        KeyValuePair<string, ServerRuntime>[] runtimes;
        lock (_lock)
        {
            runtimes = [.. _runtimes];
            _runtimes.Clear();
        }

        foreach (var (name, runtime) in runtimes)
        {
            await runtime.DisposeAsync().ConfigureAwait(false);
            if (runtime.HasExited)
            {
                // 處置後確認行程已結束才移除登記，避免異常未終止行程被從清單中抹除
                _registry.Remove(name);
            }
            else
            {
                Logger.Warning("伺服器「{Server}」行程於處置後尚未結束，保留其在 running_servers.json 的登記", name);
            }
        }

        await _registry.FlushAsync().ConfigureAwait(false);
    }
}
