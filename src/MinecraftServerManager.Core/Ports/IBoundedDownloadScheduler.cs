namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 下載工作執行狀態。
/// </summary>
public enum DownloadTaskState
{
    Queued,
    Downloading,
    Completed,
    Failed,
    Cancelled,
}

/// <summary>
/// 單一下載工作進度。
/// </summary>
public sealed record DownloadTaskProgress(
    string TaskId,
    DownloadTaskState State,
    int CompletedCount,
    int TotalCount);

/// <summary>
/// 單一下載工作的執行結果。
/// </summary>
public sealed record DownloadTaskResult<TResult>(
    string TaskId,
    TResult? Value,
    Exception? Error = null,
    bool IsCancelled = false);

/// <summary>
/// 以全域與來源限制執行下載工作。
/// </summary>
public interface IBoundedDownloadScheduler
{
    public Task<IReadOnlyList<DownloadTaskResult<TResult>>> ExecuteAsync<TResult>(
        IReadOnlyList<IDownloadTask<TResult>> tasks,
        IProgress<DownloadTaskProgress>? progress = null,
        CancellationToken cancellationToken = default);
}
