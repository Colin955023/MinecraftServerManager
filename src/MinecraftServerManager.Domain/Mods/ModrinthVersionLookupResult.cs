namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 以檔案雜湊查詢遠端模組平台版本之結果
/// </summary>
public sealed record ModrinthVersionLookupResult
{
    public string Algorithm { get; }
    public string ProjectId { get; }
    public OnlineModVersion Version { get; }

    public ModrinthVersionLookupResult(
        string algorithm,
        string projectId,
        OnlineModVersion version)
    {
        Algorithm = algorithm ?? string.Empty;
        ProjectId = projectId ?? string.Empty;
        ArgumentNullException.ThrowIfNull(version);
        Version = version;
    }
}
