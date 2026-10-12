using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// Modrinth REST API 查詢服務抽象介面
/// </summary>
public interface IModrinthClient
{
    /// <summary>
    /// 依關鍵字、載入器與 Minecraft 版本搜尋線上模組
    /// </summary>
    public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
        string query,
        string? loader = null,
        string? minecraftVersion = null,
        int limit = 20,
        int offset = 0,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 取得指定專案的所有發布版本清單
    /// </summary>
    public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
        string projectIdOrSlug,
        string? loader = null,
        string? minecraftVersion = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 依檔案雜湊查詢版本資訊
    /// </summary>
    public Task<ModrinthVersionLookupResult?> LookupVersionByHashAsync(
        string hash,
        string algorithm = "sha512",
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 批次以檔案雜湊清單查詢版本資訊
    /// </summary>
    public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
        IReadOnlyList<string> hashes,
        string algorithm = "sha512",
        CancellationToken cancellationToken = default);
}
