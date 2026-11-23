namespace MinecraftServerManager.App.ViewModels;

/// <summary>可向宿主視窗發出關閉請求的 ViewModel 介面</summary>
public interface IDialogCloseRequester
{
    public event Action<bool>? RequestClose;
}

/// <summary>具備未儲存變更關閉前確認提示的對話框 ViewModel 介面</summary>
public interface IUnsavedChangesPrompt
{
    public bool HasUnsavedChanges { get; }

    public Task<bool> ConfirmDiscardAsync();
}

/// <summary>對話視窗 ViewModel 基底類別：提供關閉要求、生命週期取消權杖與一致釋放流程</summary>
public abstract class DialogViewModelBase : ViewModelBase, IDialogCloseRequester, IDisposable
{
    private CancellationTokenSource? _lifetime;
    private int _disposed;

    public event Action<bool>? RequestClose;

    protected bool IsDisposed => Volatile.Read(ref _disposed) != 0;

    /// <summary>生命週期取消權杖；釋放後回傳已取消的權杖</summary>
    protected CancellationToken LifetimeToken
    {
        get
        {
            if (IsDisposed)
            {
                return new CancellationToken(canceled: true);
            }

            var lifetime = Volatile.Read(ref _lifetime);
            if (lifetime is null)
            {
                var created = new CancellationTokenSource();
                lifetime = Interlocked.CompareExchange(ref _lifetime, created, null) ?? created;
                if (!ReferenceEquals(lifetime, created))
                {
                    created.Dispose();
                }
            }

            return lifetime.Token;
        }
    }

    protected void Close(bool success) => RequestClose?.Invoke(success);

    protected virtual void OnDispose()
    {
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        var lifetime = Interlocked.Exchange(ref _lifetime, null);
        lifetime?.Cancel();
        OnDispose();
        lifetime?.Dispose();
        GC.SuppressFinalize(this);
    }
}
