namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器建立狀態
/// </summary>
public enum CreationStatus
{
    Completed,
    Cancelled,
    Failed
}

/// <summary>
/// 伺服器匯入模式
/// </summary>
public enum ImportMode
{
    Import,
    Redetect
}

/// <summary>
/// 伺服器匯入傳輸模式
/// </summary>
public enum ImportTransferMode
{
    Copy,
    Move
}

/// <summary>
/// 匯入來源類型
/// </summary>
public enum ImportSourceKind
{
    Archive,
    Directory,
    InPlace
}

/// <summary>
/// 伺服器匯入狀態
/// </summary>
public enum ImportStatus
{
    Completed,
    Skipped,
    Cancelled,
    Failed
}

/// <summary>
/// 衝突類型
/// </summary>
public enum ConflictType
{
    None,
    Disk,
    Config,
    Both
}

/// <summary>
/// 伺服器檢查用途
/// </summary>
public enum InspectionPurpose
{
    Import,
    Redetect,
    Status,
    Launch
}

/// <summary>
/// EULA 接受狀態
/// </summary>
public enum EulaState
{
    Missing,
    Accepted,
    Rejected,
    Unreadable
}

/// <summary>
/// 啟動目標種類
/// </summary>
public enum LaunchTargetKind
{
    Script,
    Jar,
    Args,
    None
}
