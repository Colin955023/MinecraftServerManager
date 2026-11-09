namespace MinecraftServerManager.Core.Servers;

public enum ServerPropertiesReadStatus
{
    Ok,
    Missing,
    Empty,
    Invalid,
    Unreadable,
}

public enum ServerPropertiesUpdateError
{
    None,
    ReadFailed,
    Conflict,
    Invalid,
    WriteFailed,
}

/// <summary>
/// server.properties 不可變快照與內容修訂版本
/// </summary>
public sealed record ServerPropertiesSnapshot(
    string ServerName,
    ServerPropertiesReadStatus Status,
    string Revision,
    IReadOnlyDictionary<string, string> Properties,
    string Message = "")
{
    public bool Readable => Status is ServerPropertiesReadStatus.Ok or ServerPropertiesReadStatus.Empty or ServerPropertiesReadStatus.Missing;
}

public sealed record ServerPropertiesUpdateResult(
    bool Success,
    ServerPropertiesSnapshot Snapshot,
    ServerPropertiesUpdateError ErrorKind = ServerPropertiesUpdateError.None,
    string Message = "");
