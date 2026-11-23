using System.Collections.Concurrent;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 同鍵並發請求共用同一次非同步工作；工作完成（含失敗）後自字典移除，下次呼叫重新執行。
/// 呼叫端取消只停止其等待，不取消共用工作。
/// </summary>
public sealed class SingleFlight<TKey, TValue>(IEqualityComparer<TKey>? comparer = null)
    where TKey : notnull
{
    private readonly ConcurrentDictionary<TKey, Lazy<Task<TValue>>> _inFlight = new(comparer);

    /// <summary>取得同鍵進行中工作的結果；沒有進行中工作時以 <paramref name="factory"/> 啟動一次</summary>
    public Task<TValue> WaitAsync(TKey key, Func<TKey, Task<TValue>> factory, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(factory);
        var lazy = _inFlight.GetOrAdd(key, k => new Lazy<Task<TValue>>(() => RunAsync(k, factory)));
        return lazy.Value.WaitAsync(cancellationToken);
    }

    private async Task<TValue> RunAsync(TKey key, Func<TKey, Task<TValue>> factory)
    {
        try
        {
            return await factory(key).ConfigureAwait(false);
        }
        finally
        {
            _inFlight.TryRemove(key, out _);
        }
    }
}
