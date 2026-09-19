namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 由伺服器檢查選出的唯一啟動目標
/// </summary>
public sealed record ServerLaunchTarget
{
    public LaunchTargetKind Kind { get; }
    public string Value { get; }
    public string Command { get; }
    public IReadOnlyList<string> Candidates { get; }
    public string Reason { get; }

    public ServerLaunchTarget(
        LaunchTargetKind kind,
        string value = "",
        string command = "",
        IEnumerable<string>? candidates = null,
        string reason = "")
    {
        Kind = kind;
        Value = value ?? string.Empty;
        Command = command ?? string.Empty;
        Candidates = (candidates ?? []).ToArray();
        Reason = reason ?? string.Empty;
    }

    public static ServerLaunchTarget None(string reason = "") =>
        new(LaunchTargetKind.None, reason: reason);
}
