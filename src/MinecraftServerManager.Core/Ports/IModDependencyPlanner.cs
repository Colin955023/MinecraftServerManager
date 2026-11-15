using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>模組版本相容性與相依性評估規劃介面</summary>
public interface IModDependencyPlanner
{
    /// <summary>評估目標模組版本在目前伺服器環境之相容性與相依性狀態</summary>
    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? serverSide = null);

    /// <summary>遞迴解析未安裝的必要相依（upgradeInstalled=false 時已安裝者略過）</summary>
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
