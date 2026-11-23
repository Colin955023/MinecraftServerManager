namespace MinecraftServerManager.Core.Ports;

/// <summary>依 Mojang 官方資料取得並快取 Java major 需求</summary>
public interface IMinecraftJavaRequirementService
{
    /// <summary>取得指定 Minecraft 版本與載入器所需的 Java major</summary>
    public Task<int> GetRequiredJavaMajorAsync(string minecraftVersion, CancellationToken cancellationToken = default);

    /// <summary>從快取同步取得指定的 Java 主要版本；未快取時回傳 null</summary>
    public int? GetCachedJavaMajor(string minecraftVersion);

    /// <summary>預載所有正式版的 Java major 需求至快取</summary>
    public Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(bool force = false, CancellationToken cancellationToken = default);

    /// <summary>取得本機版本快取中排序後不重複的 Java 主要版本清單</summary>
    public IReadOnlyList<int> GetCachedAvailableJavaMajors();

    /// <summary>重新載入本機快取至記憶體快取</summary>
    public void ReloadCache();
}
