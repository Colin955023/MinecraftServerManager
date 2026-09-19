namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 本地模組狀態
/// </summary>
public enum ModStatus
{
    Enabled,
    Disabled
}

/// <summary>
/// 模組來源平台
/// </summary>
public enum ModPlatform
{
    Local,
    Modrinth
}

/// <summary>
/// 模組相依性類型
/// </summary>
public enum ModDependencyType
{
    Required,
    Optional,
    Incompatible,
    Embedded
}
