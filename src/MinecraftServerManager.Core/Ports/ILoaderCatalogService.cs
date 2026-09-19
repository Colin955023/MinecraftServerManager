using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// Minecraft 與各載入器版本目錄查詢服務抽象介面
/// </summary>
public interface ILoaderCatalogService
{
    /// <summary>
    /// 取得支援的官方 Minecraft 版本清單
    /// </summary>
    public Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 取得指定 Minecraft 版本下相容的 Loader 版本清單
    /// </summary>
    public Task<IReadOnlyList<LoaderVersion>> GetLoaderVersionsAsync(
        LoaderKind loader,
        string minecraftVersion,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 強制重新整理並快取所有載入器版本（Fabric, Quilt, Forge, NeoForge）
    /// </summary>
    public Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// 重新載入並遞補合併最新 Minecraft 版本清單
    /// </summary>
    public Task<IReadOnlyList<LoaderVersion>> ReloadAndMergeMinecraftVersionsAsync(
        bool includeSnapshots = false,
        CancellationToken cancellationToken = default);
}
