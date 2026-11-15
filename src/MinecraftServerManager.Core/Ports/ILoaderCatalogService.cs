using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>Minecraft 與各載入器版本目錄查詢服務介面</summary>
public interface ILoaderCatalogService
{
    /// <summary>取得載入器支援的 Minecraft 版本清單</summary>
    public Task<IReadOnlyList<LoaderVersion>> GetMinecraftVersionsForLoaderAsync(
        LoaderKind loader,
        bool includeSnapshots = false,
        bool forceReload = false,
        CancellationToken cancellationToken = default);

    /// <summary>取得 Paper 支援的 Minecraft 版本及其 Java major</summary>
    public Task<IReadOnlyList<LoaderVersion>> GetPaperMinecraftVersionsAsync(
        bool forceReload = false,
        CancellationToken cancellationToken = default);

    /// <summary>取得指定 Minecraft 版本下相容的 Loader 版本清單</summary>
    public Task<IReadOnlyList<LoaderVersion>> GetLoaderVersionsAsync(
        LoaderKind loader,
        string minecraftVersion,
        CancellationToken cancellationToken = default);

    /// <summary>重新整理所有載入器版本快取</summary>
    public Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default);

    /// <summary>背景預熱載入器版本快取（僅在快取過期或不存在時自遠端更新）</summary>
    public Task WarmupLoadersAsync(CancellationToken cancellationToken = default);
}
