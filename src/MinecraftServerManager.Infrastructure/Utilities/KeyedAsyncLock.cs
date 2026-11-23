using System.Collections.Concurrent;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>依鍵值（預設不分大小寫）序列化非同步作業的互斥鎖</summary>
internal sealed class KeyedAsyncLock(IEqualityComparer<string>? comparer = null)
{
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _gates = new(comparer ?? StringComparer.OrdinalIgnoreCase);

    /// <summary>取得指定鍵值的鎖；以 <c>using</c> 釋放</summary>
    public async Task<Releaser> AcquireAsync(string key, CancellationToken cancellationToken = default)
    {
        SemaphoreSlim gate = _gates.GetOrAdd(key, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        return new Releaser(gate);
    }

    /// <summary>釋放已取得的鎖</summary>
    public readonly struct Releaser(SemaphoreSlim gate) : IDisposable
    {
        public void Dispose() => gate.Release();
    }
}
