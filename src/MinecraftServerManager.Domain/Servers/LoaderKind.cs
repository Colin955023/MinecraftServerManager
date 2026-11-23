namespace MinecraftServerManager.Domain.Servers;

/// <summary>支援的 Minecraft 伺服器載入器類型</summary>
public enum LoaderKind
{
    Unknown,
    Paper,
    Fabric,
    Forge,
    NeoForge,
    Quilt,
    Vanilla,
}
