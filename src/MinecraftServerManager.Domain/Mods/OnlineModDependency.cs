namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組版本宣告之相依性
/// </summary>
public sealed record OnlineModDependency(
    string? VersionId,
    string? ProjectId,
    string? FileName,
    ModDependencyType DependencyType)
{
    public OnlineModDependency(string? projectId, ModDependencyType dependencyType)
        : this(null, projectId, null, dependencyType)
    {
    }
}
