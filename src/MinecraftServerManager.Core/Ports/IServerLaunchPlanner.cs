using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器啟動規劃器契約介面</summary>
public interface IServerLaunchPlanner
{
    /// <summary>依伺服器設定與啟動目標建立啟動計畫；<paramref name="javaMajor"/> 用於挑選 GC 與原生存取建議參數</summary>
    public ServerLaunchPlan CreatePlan(ServerConfig config, string launchTarget, string? javaPath = null, int? javaMajor = null);
}
