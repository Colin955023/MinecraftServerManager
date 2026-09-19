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
        IReadOnlyList<LocalModInfo> installedMods);
}
