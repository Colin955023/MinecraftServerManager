namespace MinecraftServerManager.Domain.Servers;

/// <summary>伺服器匯入傳輸模式</summary>
public enum ImportTransferMode
{
    Copy,
    Move
}

/// <summary>啟動目標種類</summary>
public enum LaunchTargetKind
{
    Script,
    Jar,
    None
}
