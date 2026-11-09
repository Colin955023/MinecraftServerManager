namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組相容性與相依性分析結果（缺少必要相依與衝突模組皆會同時列入 <see cref="HardErrors"/>）
/// </summary>
public sealed record OnlineModCompatibilityReport(
    IReadOnlyList<string> HardErrors,
    IReadOnlyList<string> MissingRequiredDependencies,
    IReadOnlyList<string> IncompatibleInstalled)
{
    public bool IsCompatible => HardErrors.Count == 0;
}
