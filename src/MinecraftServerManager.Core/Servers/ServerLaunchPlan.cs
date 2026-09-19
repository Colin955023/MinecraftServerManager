using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// 伺服器啟動計畫（強型別不可變模型）
/// </summary>
public sealed record ServerLaunchPlan(
    string JavaExecutable,
    string WorkingDirectory,
    IReadOnlyList<string> Arguments,
    LoaderKind Loader,
    int MinMemoryMb,
    int MaxMemoryMb,
    bool IsScript);

/// <summary>
/// 伺服器啟動規劃器契約介面
/// </summary>
public interface IServerLaunchPlanner
{
    /// <summary>
    /// 依據伺服器設定與診斷結果建立啟動計畫
    /// </summary>
    public ServerLaunchPlan CreatePlan(ServerConfig config, ServerInspection inspection, string? javaPath = null);
}
