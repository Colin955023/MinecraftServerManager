namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 以檔案雜湊查詢遠端模組平台版本之結果
/// </summary>
public sealed record ModrinthVersionLookupResult
{
    public string FileHash { get; }
    public string Algorithm { get; }
    public string ProjectId { get; }
    public OnlineModVersion Version { get; }

    public ModrinthVersionLookupResult(
        string fileHash,
        string algorithm,
        string projectId,
        OnlineModVersion version)
    {
        FileHash = fileHash ?? string.Empty;
        Algorithm = algorithm ?? string.Empty;
        ProjectId = projectId ?? string.Empty;
        Version = version ?? throw new ArgumentNullException(nameof(version));
    }
}
