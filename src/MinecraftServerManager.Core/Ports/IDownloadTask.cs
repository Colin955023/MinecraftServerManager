namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 可由有界下載排程器執行的單一下載工作。
/// </summary>
public interface IDownloadTask<TResult>
{
    public string Id { get; }

    public Uri SourceUri { get; }

    public string ResourceKey { get; }

    public DownloadTaskState GetResultState(TResult result);

    public Task<TResult> ExecuteAsync(CancellationToken cancellationToken);
}

/// <summary>
/// 以委派定義的下載工作。
/// </summary>
public sealed class DelegateDownloadTask<TResult>(
    string id,
    Uri sourceUri,
    string resourceKey,
    Func<CancellationToken, Task<TResult>> executeAsync,
    Func<TResult, DownloadTaskState>? getResultState = null) : IDownloadTask<TResult>
{
    public string Id { get; } = string.IsNullOrWhiteSpace(id)
        ? throw new ArgumentException("工作識別碼不可為空。", nameof(id))
        : id;

    public Uri SourceUri { get; } = sourceUri is { IsAbsoluteUri: true }
        ? sourceUri
        : throw new ArgumentException("下載來源必須是絕對 URI。", nameof(sourceUri));

    public string ResourceKey { get; } = resourceKey ?? throw new ArgumentNullException(nameof(resourceKey));

    private readonly Func<CancellationToken, Task<TResult>> _executeAsync = executeAsync
        ?? throw new ArgumentNullException(nameof(executeAsync));
    private readonly Func<TResult, DownloadTaskState> _getResultState = getResultState ?? (_ => DownloadTaskState.Completed);

    public Task<TResult> ExecuteAsync(CancellationToken cancellationToken) => _executeAsync(cancellationToken);

    public DownloadTaskState GetResultState(TResult result) => _getResultState(result);
}
