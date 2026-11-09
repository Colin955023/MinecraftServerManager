namespace MinecraftServerManager.Core.Utilities;

/// <summary>
/// 同步進度轉接器：於回報執行緒直接呼叫處理委派，不擷取 SynchronizationContext，
/// 避免巢狀 <see cref="Progress{T}"/> 重複派送造成延遲與回報亂序。
/// </summary>
public sealed class SynchronousProgress<T>(Action<T> handler) : IProgress<T>
{
    private readonly Action<T> _handler = handler ?? throw new ArgumentNullException(nameof(handler));

    public void Report(T value) => _handler(value);
}
