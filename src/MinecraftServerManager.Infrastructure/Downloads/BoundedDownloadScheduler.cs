using System.Collections.Concurrent;
using System.Threading.Channels;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.Infrastructure.Downloads;

/// <summary>
/// 以有界通道、全域併行上限及來源限制執行下載工作。
/// </summary>
public sealed class BoundedDownloadScheduler : IBoundedDownloadScheduler, IDisposable
{
    private readonly int _maxConcurrentDownloads;
    private readonly int _maxPerSource;
    private readonly SemaphoreSlim _globalGate;
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _sourceGates = new(StringComparer.OrdinalIgnoreCase);
    private bool _disposed;

    public BoundedDownloadScheduler(int maxConcurrentDownloads = 4, int maxPerSource = 2)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(maxConcurrentDownloads, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(maxPerSource, 1);
        _maxConcurrentDownloads = maxConcurrentDownloads;
        _maxPerSource = maxPerSource;
        _globalGate = new SemaphoreSlim(maxConcurrentDownloads, maxConcurrentDownloads);
    }

    public async Task<IReadOnlyList<DownloadTaskResult<TResult>>> ExecuteAsync<TResult>(
        IReadOnlyList<IDownloadTask<TResult>> tasks,
        IProgress<DownloadTaskProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (tasks.Count == 0)
        {
            return [];
        }
        if (tasks.Any(static task => task is null))
        {
            throw new ArgumentException("下載工作不可包含空值。", nameof(tasks));
        }

        var resourceGates = new ConcurrentDictionary<string, SemaphoreSlim>(StringComparer.OrdinalIgnoreCase);
        var results = new DownloadTaskResult<TResult>[tasks.Count];
        var channel = Channel.CreateBounded<WorkItem<TResult>>(new BoundedChannelOptions(_maxConcurrentDownloads)
        {
            FullMode = BoundedChannelFullMode.Wait,
            SingleReader = false,
            SingleWriter = true,
        });
        int workerCount = Math.Min(_maxConcurrentDownloads, tasks.Count);
        int completedCount = 0;
        Task[] workers = [.. Enumerable.Range(0, workerCount)
            .Select(_ => ConsumeAsync(
                channel.Reader,
                results,
                resourceGates,
                progress,
                tasks.Count,
                () => Volatile.Read(ref completedCount),
                () => Interlocked.Increment(ref completedCount),
                cancellationToken))];

        try
        {
            for (int i = 0; i < tasks.Count; i++)
            {
                IDownloadTask<TResult> task = tasks[i];
                ReportProgress(progress, new(task.Id, DownloadTaskState.Queued, Volatile.Read(ref completedCount), tasks.Count));
                await channel.Writer.WriteAsync(new WorkItem<TResult>(i, task), CancellationToken.None).ConfigureAwait(false);
            }
        }
        finally
        {
            channel.Writer.TryComplete();
        }

        await Task.WhenAll(workers).ConfigureAwait(false);
        foreach (SemaphoreSlim gate in resourceGates.Values)
        {
            gate.Dispose();
        }

        return results;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _globalGate.Dispose();
        foreach (SemaphoreSlim gate in _sourceGates.Values)
        {
            gate.Dispose();
        }
        _sourceGates.Clear();
    }

    private async Task ConsumeAsync<TResult>(
        ChannelReader<WorkItem<TResult>> reader,
        DownloadTaskResult<TResult>[] results,
        ConcurrentDictionary<string, SemaphoreSlim> resourceGates,
        IProgress<DownloadTaskProgress>? progress,
        int totalCount,
        Func<int> getCompletedCount,
        Func<int> incrementCompleted,
        CancellationToken cancellationToken)
    {
        await foreach (WorkItem<TResult> workItem in reader.ReadAllAsync(CancellationToken.None).ConfigureAwait(false))
        {
            IDownloadTask<TResult> task = workItem.Task;
            SemaphoreSlim? resourceGate = string.IsNullOrWhiteSpace(task.ResourceKey)
                ? null
                : resourceGates.GetOrAdd(task.ResourceKey, static _ => new SemaphoreSlim(1, 1));
            SemaphoreSlim sourceGate = _sourceGates.GetOrAdd(
                task.SourceUri.Authority,
                _ => new SemaphoreSlim(_maxPerSource, _maxPerSource));
            bool resourceEntered = false;
            bool sourceEntered = false;
            bool globalEntered = false;
            TResult? value = default;
            Exception? error = null;
            bool cancelled = false;
            DownloadTaskState state;

            try
            {
                if (resourceGate is not null)
                {
                    await resourceGate.WaitAsync(cancellationToken).ConfigureAwait(false);
                    resourceEntered = true;
                }

                await sourceGate.WaitAsync(cancellationToken).ConfigureAwait(false);
                sourceEntered = true;
                await _globalGate.WaitAsync(cancellationToken).ConfigureAwait(false);
                globalEntered = true;

                ReportProgress(progress, new(task.Id, DownloadTaskState.Downloading, getCompletedCount(), totalCount));
                value = await task.ExecuteAsync(cancellationToken).ConfigureAwait(false);
                state = task.GetResultState(value);
                if (state is DownloadTaskState.Queued or DownloadTaskState.Downloading)
                {
                    state = DownloadTaskState.Failed;
                }
                cancelled = state == DownloadTaskState.Cancelled;
            }
            catch (OperationCanceledException ex) when (cancellationToken.IsCancellationRequested)
            {
                cancelled = true;
                state = DownloadTaskState.Cancelled;
                error = ex;
            }
            catch (Exception ex)
            {
                state = DownloadTaskState.Failed;
                error = ex;
            }
            finally
            {
                if (globalEntered)
                {
                    _globalGate.Release();
                }
                if (sourceEntered)
                {
                    sourceGate.Release();
                }
                if (resourceEntered)
                {
                    resourceGate!.Release();
                }
            }

            int completed = incrementCompleted();
            results[workItem.Index] = new(task.Id, value, error, cancelled);
            ReportProgress(progress, new(task.Id, state, completed, totalCount));
        }
    }

    private static void ReportProgress(IProgress<DownloadTaskProgress>? progress, DownloadTaskProgress value)
    {
        try
        {
            progress?.Report(value);
        }
        catch
        {
            // 進度回呼失敗不應中斷下載工作。
        }
    }

    private sealed record WorkItem<TResult>(int Index, IDownloadTask<TResult> Task);
}
