using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 模組版本相容性與相依性評估規劃抽象介面
/// </summary>
public interface IModDependencyPlanner
{
    /// <summary>
    /// 評估目標模組版本在目前伺服器環境之相容性與相依性狀態
    /// </summary>
    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? serverSide = null);

    /// <summary>
    /// 遞迴解析目標模組版本所需之所有未安裝必要相依項（有界 BFS 探索，防止循環相依與爆炸）
    /// </summary>
    /// <param name="modrinthClient">Modrinth API 用戶端</param>
    /// <param name="initialDependencies">初始待解析相依項集合</param>
    /// <param name="serverMinecraftVersion">伺服器 Minecraft 版本</param>
    /// <param name="serverLoader">伺服器載入器</param>
    /// <param name="installedMods">目前已安裝模組清單</param>
    /// <param name="maxDepth">最大探索深度（預設 5）</param>
    /// <param name="maxItems">最大探索解析項目上限（預設 20）</param>
    /// <param name="cancellationToken">取消語彙基元</param>
    /// <returns>需補充安裝或更新之相依計畫清單</returns>
    public Task<IReadOnlyList<ModDependencyPlanItem>> ResolveDependenciesRecursivelyAsync(
        IModrinthClient modrinthClient,
        IReadOnlyList<OnlineModDependency> initialDependencies,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        int maxDepth = 5,
        int maxItems = 20,
        CancellationToken cancellationToken = default);
}
