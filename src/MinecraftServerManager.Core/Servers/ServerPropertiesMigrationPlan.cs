namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// 伺服器屬性遷移計畫
/// </summary>
public sealed record ServerPropertiesMigrationPlan(
    bool NeedsMigration,
    IReadOnlyList<string> Changes,
    IReadOnlyDictionary<string, string> MigratedProperties);
