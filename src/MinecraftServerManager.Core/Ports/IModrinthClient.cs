using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>Modrinth REST API 查詢服務介面</summary>
public interface IModrinthClient
{
    /// <summary>依關鍵字、載入器與 Minecraft 版本搜尋線上模組</summary>
    public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        string? loader = null,
        string? minecraftVersion = null,
        int limit = 20,
        int offset = 0,
        string index = "relevance",
        CancellationToken cancellationToken = default);

    /// <summary>取得指定專案的所有發布版本清單</summary>
    public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
        string projectIdOrSlug,
        string? loader = null,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default);

    /// <summary>批次以檔案雜湊清單查詢版本資訊</summary>
    public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
        IReadOnlyList<string> hashes,
        string algorithm = "sha512",
        CancellationToken cancellationToken = default);

    /// <summary>批次取得專案名稱（以輸入的 ID 或 slug 為鍵；查不到者不列入）</summary>
    public Task<IReadOnlyDictionary<string, string>> GetProjectTitlesAsync(
        IReadOnlyCollection<string> projectIdsOrSlugs,
        CancellationToken cancellationToken = default);
}
