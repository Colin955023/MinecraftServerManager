using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>測試用多伺服器執行階段管理：以名稱（不分大小寫）管理多個 <see cref="FakeServerRuntime"/></summary>
internal sealed class FakeServerRuntimeHost : IServerRuntimeHost
{
    private readonly Dictionary<string, IServerRuntime> _runtimes = new(StringComparer.OrdinalIgnoreCase);

    public int SubscriberCount => ServerStateChanged?.GetInvocationList().Length ?? 0;

    public bool IsAnyRunning => _runtimes.Values.Any(static r => r.IsRunning);

    /// <summary>登錄指定名稱使用的自訂執行階段替身</summary>
    public void Add(string name, IServerRuntime runtime) => _runtimes[name] = runtime;

    public event Action<string>? ServerStateChanged;

    public FakeServerRuntime GetFake(string name)
    {
        if (!_runtimes.TryGetValue(name, out var runtime))
        {
            runtime = new FakeServerRuntime();
            _runtimes[name] = runtime;
        }

        return (FakeServerRuntime)runtime;
    }

    public IServerRuntime GetRuntime(string serverName) =>
        _runtimes.TryGetValue(serverName, out var runtime) ? runtime : GetFake(serverName);

    public bool IsRunning(string serverName) => _runtimes.TryGetValue(serverName, out var r) && r.IsRunning;

    public IReadOnlyList<string> GetRunningServerNames() => [.. _runtimes.Where(static p => p.Value.IsRunning).Select(static p => p.Key)];

    public void RaiseStateChanged(string name) => ServerStateChanged?.Invoke(name);

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
