namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// Minecraft 版本的 Java 主要版本 (majorVersion) 需求服務。
/// 核心依據 Mojang 官方 version package 中的 javaVersion.majorVersion 動態取得並快取，
/// 嚴禁以 Minecraft 版本號進行任何硬編碼推算。
/// </summary>
public interface IMinecraftJavaRequirementService
{
    /// <summary>
    /// 依據 Minecraft 版本非同步取得官方指定的 Java 主要版本
    /// </summary>
    /// <param name="minecraftVersion">Minecraft 版本字串 (例如 "1.21.4")</param>
    /// <param name="cancellationToken">取消語彙基元</param>
    /// <returns>官方指定的 Java 主要版本 (例如 21, 17, 8)</returns>
    public Task<int> GetRequiredJavaMajorAsync(string minecraftVersion, CancellationToken cancellationToken = default);

    /// <summary>
    /// 從快取同步取得官方指定的 Java 主要版本；若快取未載入或尚未包含此版本則回傳 null
    /// </summary>
    /// <param name="minecraftVersion">Minecraft 版本字串</param>
    /// <returns>官方指定的 Java 主要版本，未快取時回傳 null</returns>
    public int? GetCachedJavaMajor(string minecraftVersion);

    /// <summary>
    /// 平行非同步預載入官方 Manifest 中所有 release 版本的 Java major 需求至快取檔案
    /// </summary>
    /// <param name="force">是否強制忽略現有快取重新抓取</param>
    /// <param name="cancellationToken">取消語彙基元</param>
    /// <returns>版本與 Java major 映射字典</returns>
    public Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(bool force = false, CancellationToken cancellationToken = default);
}
