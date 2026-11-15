namespace MinecraftServerManager.Domain.Mods;

/// <summary>線上模組相容性與相依性分析結果</summary>
public sealed record OnlineModCompatibilityReport(
    IReadOnlyList<string> HardErrors,
    IReadOnlyList<string> MissingRequiredDependencies,
    IReadOnlyList<string> IncompatibleInstalled)
{
    /// <summary>是否環境不相容（伺服器端、載入器或 Minecraft 版本不符）</summary>
    public bool HasEnvironmentErrors =>
        HardErrors.Count - IncompatibleInstalled.Count - (MissingRequiredDependencies.Count > 0 ? 1 : 0) > 0;
}
