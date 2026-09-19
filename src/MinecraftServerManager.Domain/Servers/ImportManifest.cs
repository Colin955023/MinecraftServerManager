namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 匯入來源內單一檔案的不可變快照
/// </summary>
public sealed record ImportManifestEntry(
    string RelativePath,
    long Size,
    long MtimeNs,
    string Sha256 = "");

/// <summary>
/// 匯入檢查與執行共用的來源檔案清單
/// </summary>
public sealed record ImportManifest
{
    public IReadOnlyList<ImportManifestEntry> Entries { get; }
    public string Revision { get; }
    public long TotalBytes { get; }

    public ImportManifest(IEnumerable<ImportManifestEntry> entries, string revision, long totalBytes)
    {
        Entries = (entries ?? []).ToArray();
        Revision = revision ?? string.Empty;
        TotalBytes = totalBytes;
    }
}
