namespace MinecraftServerManager.Domain.Mods;

/// <summary>線上模組相容性與相依性分析結果（缺少必要相依與衝突模組皆會同時列入 <see cref="HardErrors"/>）</summary>
public sealed record OnlineModCompatibilityReport(
    IReadOnlyList<string> HardErrors,
    IReadOnlyList<string> MissingRequiredDependencies,
    IReadOnlyList<string> IncompatibleInstalled)
{
    /// <summary>是否有環境不相容（伺服器端、載入器或 Minecraft 版本不符）；不含缺少必要相依與衝突模組</summary>
    public bool HasEnvironmentErrors =>
        HardErrors.Count - IncompatibleInstalled.Count - (MissingRequiredDependencies.Count > 0 ? 1 : 0) > 0;
}
