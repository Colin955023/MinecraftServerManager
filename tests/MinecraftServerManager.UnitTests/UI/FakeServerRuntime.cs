using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 測試用伺服器執行階段：可手動觸發事件並記錄訂閱數與啟停呼叫
/// </summary>
internal sealed class FakeServerRuntime : IServerRuntime
{
    public int Pid => 1234;
    public bool IsRunning { get; set; }
    public bool IsReady { get; set; }
    public int? ExitCode { get; set; } = 0;
    public string? ActiveServerName { get; set; }
    public int StartCount { get; private set; }
    public int StopCount { get; private set; }
    public ServerLaunchPlan? LastPlan { get; private set; }

    public int SubscriberCount =>
        (OutputLineReceived?.GetInvocationList().Length ?? 0) +
        (ServerExited?.GetInvocationList().Length ?? 0) +
        (ServerReady?.GetInvocationList().Length ?? 0) +
        (ServerStarted?.GetInvocationList().Length ?? 0);

    public event Action<string>? OutputLineReceived;
    public event Action<int>? ServerExited;
    public event Action? ServerReady;
    public event Action? ServerStarted;

    public void RaiseOutputLine(string line) => OutputLineReceived?.Invoke(line);
    public void RaiseExited(int exitCode) => ServerExited?.Invoke(exitCode);
    public void RaiseReady() => ServerReady?.Invoke();

    public Task StartAsync(ServerLaunchPlan plan, CancellationToken cancellationToken = default)
    {
        _ = cancellationToken;
        LastPlan = plan;
        StartCount++;
        return Task.CompletedTask;
    }

    public Task<bool> SendCommandAsync(string command, CancellationToken cancellationToken = default)
    {
        _ = command;
        _ = cancellationToken;
        return Task.FromResult(true);
    }

    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
    {
        _ = gracefulTimeout;
        _ = cancellationToken;
        StopCount++;
        IsRunning = false;
        return Task.FromResult(new ProcessExitResult(0, false));
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    public long? GetWorkingSet64() => null;
}
