using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>模組版本相容性與相依性評估規劃介面</summary>
public interface IModDependencyPlanner
{
    /// <summary>評估目標模組版本在目前伺服器環境之相容性與相依性狀態</summary>
    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        LoaderKind serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? serverSide = null);

    /// <summary>遞迴解析必要相依（upgradeInstalled=false 時已安裝者不升級）；<paramref name="rootProjectId"/> 為發起解析的模組，避免循環相依回頭安裝自身</summary>
    public Task<IReadOnlyList<ModDependencyPlanItem>> ResolveDependenciesRecursivelyAsync(
        IReadOnlyList<OnlineModDependency> initialDependencies,
        string serverMinecraftVersion,
        LoaderKind serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? rootProjectId = null,
        int maxDepth = 5,
        int maxItems = 20,
        bool upgradeInstalled = true,
        CancellationToken cancellationToken = default);
}
