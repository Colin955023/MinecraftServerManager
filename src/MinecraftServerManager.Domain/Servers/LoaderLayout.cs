using System.Collections.Frozen;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>各載入器的伺服器檔案配置：啟動 JAR 前綴、函式庫路徑與安裝器排除規則；未列於表中者皆為空值</summary>
public sealed record LoaderLayout(
    string LaunchJarPrefix,
    string LauncherJarFileName,
    string[] LibrarySegments,
    bool ExcludesInstallerJars)
{
    private static readonly LoaderLayout NoLayout = new(string.Empty, string.Empty, [], false);

    private static readonly FrozenDictionary<LoaderKind, LoaderLayout> ByKind = new Dictionary<LoaderKind, LoaderLayout>
    {
        [LoaderKind.Paper] = new("paper", string.Empty, [], false),
        [LoaderKind.Fabric] = new("fabric-server-launch", "fabric-server-launch.jar", ["net", "fabricmc", "fabric-loader"], false),
        [LoaderKind.Quilt] = new("quilt-server-launch", "quilt-server-launch.jar", ["org", "quiltmc", "quilt-loader"], false),
        [LoaderKind.Forge] = new("forge", string.Empty, ["net", "minecraftforge", "forge"], true),
        [LoaderKind.NeoForge] = new("neoforge", string.Empty, ["net", "neoforged", "neoforge"], true),
    }.ToFrozenDictionary();

    /// <summary>取得載入器的檔案配置；未知或原版載入器回傳無配置的空值</summary>
    public static LoaderLayout For(LoaderKind loader) => ByKind.GetValueOrDefault(loader, NoLayout);

    /// <summary>檔名是否為 Paper 核心 JAR（paper 前綴，不排除安裝器）</summary>
    public static bool IsPaperJarName(string fileName) => For(LoaderKind.Paper).IsLaunchJarName(fileName);

    /// <summary>檔名是否為安裝器 JAR（檔名含 installer，不分大小寫）</summary>
    public static bool IsInstallerJar(string fileName) => fileName.Contains("installer", StringComparison.OrdinalIgnoreCase);

    /// <summary>檔名是否為此載入器的啟動 JAR：前綴相符，且 Forge／NeoForge 排除安裝器</summary>
    public bool IsLaunchJarName(string fileName) =>
        LaunchJarPrefix.Length > 0
        && fileName.StartsWith(LaunchJarPrefix, StringComparison.OrdinalIgnoreCase)
        && (!ExcludesInstallerJars || !IsInstallerJar(fileName));

    /// <summary>函式庫相對伺服器根目錄之路徑（以 / 分隔），例如 libraries/net/neoforged/neoforge</summary>
    public string LibraryRelativePath => ServerDefaults.LibrariesDirectoryName + "/" + string.Join('/', LibrarySegments);
}
