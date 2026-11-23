namespace MinecraftServerManager.App.Services;

/// <summary>連續請求只保留最新者：每次 Next() 取消前一個權杖並回傳新權杖</summary>
// IDisposable 投射為 WinRT IClosable，CsWinRT 要求 partial
public sealed partial class SerialCancellation : IDisposable
{
    private readonly Lock _lock = new();
    private CancellationTokenSource? _current;
    private bool _disposed;

    /// <summary>取消前一個請求並回傳新權杖；已釋放後回傳已取消權杖</summary>
    public CancellationToken Next()
    {
        CancellationTokenSource? previous;
        CancellationToken token;
        lock (_lock)
        {
            previous = _current;
            if (_disposed)
            {
                _current = null;
                token = new CancellationToken(canceled: true);
            }
            else
            {
                var next = new CancellationTokenSource();
                _current = next;
                token = next.Token;
            }
        }

        Release(previous);
        return token;
    }

    /// <summary>取消目前請求，不建立新權杖</summary>
    public void Cancel()
    {
        CancellationTokenSource? previous;
        lock (_lock)
        {
            previous = _current;
            _current = null;
        }

        Release(previous);
    }

    public void Dispose()
    {
        lock (_lock)
        {
            _disposed = true;
        }

        Cancel();
    }

    private static void Release(CancellationTokenSource? source)
    {
        if (source is null)
        {
            return;
        }

        try
        {
            source.Cancel();
        }
        finally
        {
            source.Dispose();
        }
    }
}
