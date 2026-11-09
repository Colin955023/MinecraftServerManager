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
    bool IsScript,
    string? ServerName = null,
    IReadOnlyDictionary<string, string?>? Environment = null);

/// <summary>
/// 伺服器啟動規劃器契約介面
/// </summary>
public interface IServerLaunchPlanner
{
    /// <summary>
    /// 依據伺服器設定與啟動目標（相對伺服器目錄之 jar、bat 或 @argfile）建立啟動計畫
    /// </summary>
    public ServerLaunchPlan CreatePlan(ServerConfig config, string launchTarget, string? javaPath = null);
}
