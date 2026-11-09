using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 模組頁共用狀態：目前選取伺服器之唯讀快照與變更通知，避免子 ViewModel 互相參照
/// </summary>
public sealed class ModsContext
{
    private readonly List<Func<Task>> _modsChangedHandlers = [];

    /// <summary>
    /// 目前選取伺服器設定快照；未選取時為 null
    /// </summary>
    public ServerConfig? Server { get; private set; }

    /// <summary>
    /// Modrinth 查詢用之載入器識別碼（小寫）
    /// </summary>
    public string? LoaderId => Server?.LoaderType.ToString().ToLowerInvariant();

    /// <summary>
    /// 目前伺服器之 Minecraft 版本
    /// </summary>
    public string? MinecraftVersion => Server?.MinecraftVersion.Value;

    /// <summary>
    /// 選取伺服器變更時觸發
    /// </summary>
    public event Action? ServerChanged;

    /// <summary>
    /// 設定目前伺服器快照並通知訂閱者
    /// </summary>
    public void SetServer(ServerConfig? server)
    {
        Server = server;
        ServerChanged?.Invoke();
    }

    /// <summary>
    /// 註冊本地模組異動（安裝、更新、匯入）後之非同步處理
    /// </summary>
    public void RegisterModsChangedHandler(Func<Task> handler)
    {
        ArgumentNullException.ThrowIfNull(handler);
        _modsChangedHandlers.Add(handler);
    }

    /// <summary>
    /// 依序執行所有本地模組異動處理
    /// </summary>
    public async Task NotifyModsChangedAsync()
    {
        foreach (var handler in _modsChangedHandlers.ToArray())
        {
            await handler().ConfigureAwait(true);
        }
    }
}
