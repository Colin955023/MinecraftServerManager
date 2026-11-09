namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// 伺服器存放根目錄遷移目標路徑檢查結果
/// </summary>
public enum RelocationPathCheckResult
{
    Valid,
    EmptyTarget,
    TargetIsFile,
    SameAsCurrent,
    SubdirectoryOfCurrent,
}

/// <summary>
/// 伺服器存放根目錄遷移目標路徑檢查結果與正規化後路徑
/// </summary>
public sealed record ServersRootCheck(
    RelocationPathCheckResult Result,
    string NormalizedCurrent,
    string NormalizedNew);
