namespace MinecraftServerManager.Core.Ports;

/// <summary>依據 Mojang 官方 version package 中的 javaVersion.majorVersion 動態取得並快取 Java 主要版本需求</summary>
public interface IMinecraftJavaRequirementService
{
    /// <summary>依據 Minecraft 版本與載入器非同步取得官方或載入器指定的 Java 主要版本</summary>
    public Task<int> GetRequiredJavaMajorAsync(string minecraftVersion, Domain.Servers.LoaderKind loader = Domain.Servers.LoaderKind.Unknown, CancellationToken cancellationToken = default);

    /// <summary>從快取同步取得指定的 Java 主要版本；未快取時回傳 null</summary>
    public int? GetCachedJavaMajor(string minecraftVersion, Domain.Servers.LoaderKind loader = Domain.Servers.LoaderKind.Unknown);

    /// <summary>平行非同步預載入官方 Manifest 中所有 release 版本的 Java major 需求至快取檔案</summary>
    public Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(bool force = false, CancellationToken cancellationToken = default);

    /// <summary>取得本地版本快取中排序後不重複的 Java 主要版本清單</summary>
    public IReadOnlyList<int> GetCachedAvailableJavaMajors();

    /// <summary>重新載入本地快取至記憶體快取</summary>
    public void ReloadCache();
}
