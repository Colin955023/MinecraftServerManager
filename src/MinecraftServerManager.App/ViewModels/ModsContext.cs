using System.Diagnostics.CodeAnalysis;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組頁共用狀態：目前選取伺服器的快照與變更通知</summary>
public sealed class ModsContext
{
    private readonly List<Func<Task>> _modsChangedHandlers = [];

    /// <summary>目前選取伺服器設定快照；未選取時為 null</summary>
    public ServerConfig? Server { get; private set; }

    /// <summary>目前伺服器之載入器種類</summary>
    public LoaderKind? LoaderType => Server?.LoaderType;

    /// <summary>目前伺服器之 Minecraft 版本</summary>
    public string? MinecraftVersion => Server?.MinecraftVersion.Value;

    /// <summary>檢查目前是否已選取伺服器；未選取時以警告通知使用者並回傳 false</summary>
    public bool TryRequireServer(IUiService ui, [NotNullWhen(true)] out ServerConfig? server, string? customMessage = null)
    {
        ArgumentNullException.ThrowIfNull(ui);
        server = Server;
        if (server is null)
        {
            ui.Notify(customMessage ?? "請先選擇伺服器", NotificationType.Warning);
            return false;
        }

        return true;
    }

    /// <summary>選取伺服器變更時觸發</summary>
    public event Action? ServerChanged;

    /// <summary>設定目前伺服器快照並通知訂閱者</summary>
    public void SetServer(ServerConfig? server)
    {
        Server = server;
        ServerChanged?.Invoke();
    }

    /// <summary>註冊本地模組異動（安裝、更新、匯入）後之非同步處理</summary>
    public void RegisterModsChangedHandler(Func<Task> handler)
    {
        ArgumentNullException.ThrowIfNull(handler);
        _modsChangedHandlers.Add(handler);
    }

    /// <summary>依序執行所有本地模組異動處理</summary>
    public async Task NotifyModsChangedAsync()
    {
        foreach (var handler in _modsChangedHandlers.ToArray())
        {
            await handler();
        }
    }
}
