using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Java;

/// <summary>Java 執行環境偵測之搜尋來源</summary>
/// <param name="GetEnvironmentVariable">讀取 <c>JAVA_HOME</c>、<c>PATH</c> 等環境變數</param>
/// <param name="InstallRoots">掃描常見廠牌子目錄的安裝根目錄</param>
/// <param name="UserProfileDirectory">使用者目錄（掃描 <c>.jdks</c>）</param>
/// <param name="CacheDirectory">偵測結果快取目錄</param>
public sealed record JavaSearchSources(
    Func<string, string?> GetEnvironmentVariable,
    IReadOnlyList<string> InstallRoots,
    string? UserProfileDirectory,
    string CacheDirectory)
{
    /// <summary>以目前行程環境建立搜尋來源</summary>
    public static JavaSearchSources FromCurrentEnvironment()
    {
        var roots = new List<string>(3);
        foreach (string? root in (ReadOnlySpan<string?>)
            [RuntimePaths.GetProgramFilesDir(), RuntimePaths.GetProgramFilesX86Dir(), Environment.GetEnvironmentVariable("ProgramW6432")])
        {
            if (!string.IsNullOrWhiteSpace(root) && !roots.Contains(root, StringComparer.OrdinalIgnoreCase))
            {
                roots.Add(root);
            }
        }

        return new JavaSearchSources(
            Environment.GetEnvironmentVariable,
            roots,
            RuntimePaths.GetUserProfileDir(),
            RuntimePaths.GetVersionCacheDir());
    }
}
