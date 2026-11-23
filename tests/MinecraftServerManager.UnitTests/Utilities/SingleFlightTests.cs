using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

public sealed class SingleFlightTests
{
    [Fact]
    public async Task WaitAsync_ConcurrentCallsWithSameKey_RunsFactoryOnce()
    {
        var gate = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        int runs = 0;
        var flight = new SingleFlight<string, int>(StringComparer.OrdinalIgnoreCase);
        Task<int> Factory(string key)
        {
            Interlocked.Increment(ref runs);
            return gate.Task;
        }

        var waiters = Enumerable.Range(0, 5)
            .Select(_ => flight.WaitAsync("key", Factory, TestContext.Current.CancellationToken))
            .ToArray();
        gate.SetResult(42);
        int[] results = await Task.WhenAll(waiters);

        Assert.Equal(1, runs);
        Assert.All(results, static result => Assert.Equal(42, result));
    }

    [Fact]
    public async Task WaitAsync_AfterCompletion_RunsFactoryAgain()
    {
        int runs = 0;
        var flight = new SingleFlight<string, int>();
        Task<int> Factory(string key) => Task.FromResult(Interlocked.Increment(ref runs));

        int first = await flight.WaitAsync("key", Factory, TestContext.Current.CancellationToken);
        int second = await flight.WaitAsync("key", Factory, TestContext.Current.CancellationToken);

        Assert.Equal(1, first);
        Assert.Equal(2, second);
    }

    [Fact]
    public async Task WaitAsync_FailedRun_IsNotCachedAndRetriesOnNextCall()
    {
        int runs = 0;
        var flight = new SingleFlight<string, int>();
        Task<int> Factory(string key) =>
            Interlocked.Increment(ref runs) == 1
                ? Task.FromException<int>(new InvalidOperationException("暫時失敗"))
                : Task.FromResult(7);

        await Assert.ThrowsAsync<InvalidOperationException>(() => flight.WaitAsync("key", Factory, TestContext.Current.CancellationToken));
        int retried = await flight.WaitAsync("key", Factory, TestContext.Current.CancellationToken);

        Assert.Equal(7, retried);
        Assert.Equal(2, runs);
    }

    [Fact]
    public async Task WaitAsync_CancelledWaiter_DoesNotCancelSharedRun()
    {
        var gate = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        int runs = 0;
        var flight = new SingleFlight<string, int>();
        Task<int> Factory(string key)
        {
            Interlocked.Increment(ref runs);
            return gate.Task;
        }

        using var cancellation = new CancellationTokenSource();
        Task<int> cancelledWaiter = flight.WaitAsync("key", Factory, cancellation.Token);
        Task<int> otherWaiter = flight.WaitAsync("key", Factory, TestContext.Current.CancellationToken);

        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelledWaiter);

        gate.SetResult(9);
        int result = await otherWaiter;

        Assert.Equal(9, result);
        Assert.Equal(1, runs);
    }
}
