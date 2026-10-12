namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 模組相依性解析與安裝計畫項目
/// </summary>
public sealed record ModDependencyPlanItem(
    OnlineModVersion TargetVersion,
    ModInstallAction Action,
    LocalModInfo? ExistingLocalMod = null,
    string Reason = "");
