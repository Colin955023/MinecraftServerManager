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
    MissingServer,
    UnsafePath,
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

    public string GetProperty(string key, string fallback = "") =>
        Properties.TryGetValue(key, out string? value) ? value : fallback;

    public bool GetBoolean(string key, bool fallback = false)
    {
        if (Properties.TryGetValue(key, out string? value))
        {
            return bool.TryParse(value, out bool parsed) ? parsed : fallback;
        }

        return fallback;
    }

    public int GetInt32(string key, int fallback = 0)
    {
        if (Properties.TryGetValue(key, out string? value))
        {
            return int.TryParse(value, out int parsed) ? parsed : fallback;
        }

        return fallback;
    }
}

public sealed record ServerPropertiesUpdateResult(
    bool Success,
    ServerPropertiesSnapshot Snapshot,
    ServerPropertiesUpdateError ErrorKind = ServerPropertiesUpdateError.None,
    string Message = "");
