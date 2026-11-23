using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用伺服器執行階段：可手動觸發事件並記錄訂閱數與啟停呼叫</summary>
internal sealed class FakeServerRuntime : IServerRuntime
{
    public int Pid => 1234;
    public long? StartedTimestamp { get; set; }
    public bool IsRunning { get; set; }
    public bool IsReady { get; set; }
    public int? ExitCode { get; set; } = 0;
    public List<string> SentCommands { get; } = [];
    public Queue<ProcessExitResult?> WaitResults { get; } = new();
    public int StartCount { get; private set; }
    public int StopCount { get; private set; }
    public bool ThrowOnStop { get; set; }
    public ServerLaunchPlan? LastPlan { get; private set; }

    public int SubscriberCount =>
        (OutputLineReceived?.GetInvocationList().Length ?? 0) +
        (ServerExited?.GetInvocationList().Length ?? 0) +
        (ServerReady?.GetInvocationList().Length ?? 0) +
        (ServerStarted?.GetInvocationList().Length ?? 0);

    public event Action<string>? OutputLineReceived;
    public event Action<int>? ServerExited;
    public event Action? ServerReady;
    public event Action<int>? ServerStarted;

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
        _ = cancellationToken;
        SentCommands.Add(command);
        return Task.FromResult(true);
    }

    public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
    {
        _ = gracefulTimeout;
        _ = cancellationToken;
        StopCount++;
        if (ThrowOnStop)
        {
            throw new InvalidOperationException("停止伺服器失敗 (測試用例外)");
        }

        IsRunning = false;
        return Task.FromResult(new ProcessExitResult(0, false));
    }

    public Task<ProcessExitResult?> WaitForExitAsync(TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        _ = timeout;
        _ = cancellationToken;
        if (WaitResults.Count > 0)
        {
            var next = WaitResults.Dequeue();
            if (next is not null)
            {
                IsRunning = false;
            }

            return Task.FromResult(next);
        }

        return Task.FromResult(IsRunning ? null : new ProcessExitResult(ExitCode ?? 0, false));
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    public long? GetWorkingSet64() => null;
}
