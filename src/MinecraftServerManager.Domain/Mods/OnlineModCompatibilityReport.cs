namespace MinecraftServerManager.Domain.Mods;

/// <summary>線上模組相容性與相依性分析結果</summary>
/// <param name="HardErrors">全部阻擋安裝之錯誤訊息（含環境錯誤、衝突與缺少相依）</param>
/// <param name="MissingRequiredDependencies">缺少之必要相依</param>
/// <param name="IncompatibleInstalled">與已安裝模組衝突者</param>
/// <param name="EnvironmentErrors">伺服器端、載入器或 Minecraft 版本不符之錯誤</param>
public sealed record OnlineModCompatibilityReport(
    IReadOnlyList<string> HardErrors,
    IReadOnlyList<string> MissingRequiredDependencies,
    IReadOnlyList<string> IncompatibleInstalled,
    IReadOnlyList<string> EnvironmentErrors)
{
    /// <summary>是否環境不相容（伺服器端、載入器或 Minecraft 版本不符）</summary>
    public bool HasEnvironmentErrors => EnvironmentErrors.Count > 0;
}
