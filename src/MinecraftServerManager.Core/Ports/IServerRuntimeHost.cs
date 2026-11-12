namespace MinecraftServerManager.Core.Ports;

/// <summary>多伺服器執行階段管理抽象介面：每台伺服器各自持有一個 <see cref="IServerRuntime"/>，可同時執行</summary>
public interface IServerRuntimeHost : IAsyncDisposable
{
    /// <summary>是否有任何伺服器正在執行</summary>
    public bool IsAnyRunning { get; }

    /// <summary>任一伺服器啟動、就緒或結束時觸發，參數為伺服器名稱（可能於背景執行緒觸發）</summary>
    public event Action<string>? ServerStateChanged;

    /// <summary>取得指定伺服器的執行階段；同名伺服器（不分大小寫）一律回傳同一個執行個體</summary>
    public IServerRuntime GetRuntime(string serverName);

    /// <summary>指定伺服器是否正在執行</summary>
    public bool IsRunning(string serverName);

    /// <summary>取得目前執行中的伺服器名稱</summary>
    public IReadOnlyList<string> GetRunningServerNames();
}
