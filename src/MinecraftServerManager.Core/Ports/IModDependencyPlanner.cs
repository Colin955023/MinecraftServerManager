using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>模組版本相容性與相依性評估規劃抽象介面</summary>
public interface IModDependencyPlanner
{
    /// <summary>評估目標模組版本在目前伺服器環境之相容性與相依性狀態</summary>
    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? serverSide = null);

    /// <summary>有界 BFS 遞迴解析未安裝必要相依項（upgradeInstalled=false 時已安裝者視為已滿足並略過）</summary>
    public Task<IReadOnlyList<ModDependencyPlanItem>> ResolveDependenciesRecursivelyAsync(
        IModrinthClient modrinthClient,
        IReadOnlyList<OnlineModDependency> initialDependencies,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        int maxDepth = 5,
        int maxItems = 20,
        bool upgradeInstalled = true,
        CancellationToken cancellationToken = default);
}
