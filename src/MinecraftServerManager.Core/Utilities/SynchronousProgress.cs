namespace MinecraftServerManager.Core.Utilities;

/// <summary>同步進度轉接器：於回報執行緒直接呼叫，不擷取 SynchronizationContext</summary>
public sealed class SynchronousProgress<T> : IProgress<T>
{
    private readonly Action<T> _handler;

    public SynchronousProgress(Action<T> handler)
    {
        ArgumentNullException.ThrowIfNull(handler);
        _handler = handler;
    }

    public void Report(T value) => _handler(value);
}
