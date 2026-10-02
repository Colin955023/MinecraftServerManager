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
    /// 依據特定載入器取得支援的 Minecraft 版本清單（例如 Paper 僅提供官方支援發布之版本）
    /// </summary>
    public Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsForLoaderAsync(
        LoaderKind loader,
        bool includeSnapshots = false,
        bool forceReload = false,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 取得 PaperMC 支援的 Minecraft 官方發布版本及其所需之 Java Major 版本
    /// </summary>
    public Task<IReadOnlyList<LoaderVersion>> GetPaperMinecraftVersionsAsync(
        bool forceReload = false,
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
