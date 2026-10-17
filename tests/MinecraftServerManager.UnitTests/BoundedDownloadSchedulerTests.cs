using System.Collections.Concurrent;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Downloads;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class BoundedDownloadSchedulerTests
{
    [Fact]
    public async Task ExecuteAsync_RespectsGlobalAndPerSourceLimitsAndKeepsInputOrder()
    {
        using var scheduler = new BoundedDownloadScheduler(maxConcurrentDownloads: 4, maxPerSource: 2);
        int active = 0;
        int peakActive = 0;
        var activeBySource = new ConcurrentDictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var peakBySource = new ConcurrentDictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var tasks = Enumerable.Range(0, 12)
            .Select(index =>
            {
                string host = index % 2 == 0 ? "source-a.test" : "source-b.test";
                return (IDownloadTask<int>)new DelegateDownloadTask<int>(
                    $"task-{index}",
                    new Uri($"https://{host}/file-{index}"),
                    $"file-{index}",
                    async cancellationToken =>
                    {
                        int current = Interlocked.Increment(ref active);
                        UpdateMaximum(ref peakActive, current);
                        int sourceCurrent = activeBySource.AddOrUpdate(host, 1, static (_, count) => count + 1);
                        peakBySource.AddOrUpdate(host, sourceCurrent, (_, currentPeak) => Math.Max(currentPeak, sourceCurrent));
                        try
                        {
                            await Task.Delay(30, cancellationToken);
                            return index;
                        }
                        finally
                        {
                            activeBySource.AddOrUpdate(host, 0, static (_, count) => count - 1);
                            Interlocked.Decrement(ref active);
                        }
                    });
            })
            .ToArray();

        IReadOnlyList<DownloadTaskResult<int>> results = await scheduler.ExecuteAsync(tasks);

        Assert.Equal(4, peakActive);
        Assert.All(peakBySource.Values, static count => Assert.InRange(count, 1, 2));
        Assert.Equal(Enumerable.Range(0, 12), results.Select(static result => result.Value));
        Assert.All(results, static result => Assert.Null(result.Error));
    }

    [Fact]
    public async Task ExecuteAsync_SerializesTasksWithSameResourceKey()
    {
        using var scheduler = new BoundedDownloadScheduler(maxConcurrentDownloads: 4, maxPerSource: 4);
        int activeForResource = 0;
        int peakForResource = 0;
        var tasks = Enumerable.Range(0, 6)
            .Select(index => (IDownloadTask<int>)new DelegateDownloadTask<int>(
                $"task-{index}",
                new Uri($"https://source-{index}.test/file"),
                "same-target.jar",
                async cancellationToken =>
                {
                    int active = Interlocked.Increment(ref activeForResource);
                    UpdateMaximum(ref peakForResource, active);
                    try
                    {
                        await Task.Delay(10, cancellationToken);
                        return index;
                    }
                    finally
                    {
                        Interlocked.Decrement(ref activeForResource);
                    }
                }))
            .ToArray();

        await scheduler.ExecuteAsync(tasks);

        Assert.Equal(1, peakForResource);
    }

    [Fact]
    public async Task ExecuteAsync_RecordsPerTaskFailureAndCancellation()
    {
        using var scheduler = new BoundedDownloadScheduler(maxConcurrentDownloads: 2, maxPerSource: 2);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        IDownloadTask<int>[] failedTask =
        [new DelegateDownloadTask<int>("failed", new Uri("https://failure.test/file"), "", _ => throw new InvalidOperationException("failure"))];
        IDownloadTask<int>[] cancelledTask =
        [new DelegateDownloadTask<int>("cancelled", new Uri("https://cancel.test/file"), "", _ => Task.FromCanceled<int>(cancellation.Token))];

        IReadOnlyList<DownloadTaskResult<int>> failedResults = await scheduler.ExecuteAsync(failedTask);
        IReadOnlyList<DownloadTaskResult<int>> cancelledResults = await scheduler.ExecuteAsync(cancelledTask, cancellationToken: cancellation.Token);

        Assert.IsType<InvalidOperationException>(failedResults[0].Error);
        Assert.True(cancelledResults[0].IsCancelled);
    }

    private static void UpdateMaximum(ref int target, int value)
    {
        int current;
        while (value > (current = Volatile.Read(ref target)) &&
               Interlocked.CompareExchange(ref target, value, current) != current)
        {
        }
    }
}
