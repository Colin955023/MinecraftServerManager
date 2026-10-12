namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 本地模組的更新候選版本與相容性檢查結果
/// </summary>
public sealed record LocalModUpdateCandidate
{
    public LocalModInfo LocalMod { get; }
    public OnlineModVersion? UpdateVersion { get; }
    public OnlineModCompatibilityReport? CompatibilityReport { get; }
    public bool HasUpdate => UpdateVersion != null;

    public LocalModUpdateCandidate(
        LocalModInfo localMod,
        OnlineModVersion? updateVersion = null,
        OnlineModCompatibilityReport? compatibilityReport = null)
    {
        LocalMod = localMod ?? throw new ArgumentNullException(nameof(localMod));
        UpdateVersion = updateVersion;
        CompatibilityReport = compatibilityReport;
    }
}
