using System.Collections.Frozen;
using System.Diagnostics.CodeAnalysis;
using MinecraftServerManager.Core;
using MinecraftServerManager.Infrastructure.Http;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>更新檢查與下載共用的 GitHub Release 來源信任規則：只接受本專案官方 Release 的 HTTPS 位址</summary>
internal static class GitHubReleaseTrustPolicy
{
    private static readonly FrozenSet<string> TrustedHosts = TrustedHostPolicy.Hosts("github.com");
    private static readonly string RepositoryPath = new Uri(AppInfo.RepositoryUrl).AbsolutePath.Trim('/');
    private static readonly string ReleasesPath = $"/{RepositoryPath}/releases";
    private static readonly string AssetPathPrefix = $"/{RepositoryPath}/releases/download/";

    /// <summary>GitHub API 最新 Release 端點</summary>
    public static Uri LatestReleaseUri { get; } = new($"https://api.github.com/repos/{RepositoryPath}/releases/latest");

    /// <summary>Release 清單頁</summary>
    public static string DefaultReleasePageUrl { get; } = AppInfo.RepositoryUrl + "/releases";

    /// <summary>是否為本專案 Release 附件下載位址</summary>
    public static bool IsTrustedAssetUrl(string? url) =>
        TryParseTrusted(url, out Uri? uri) &&
        uri.AbsolutePath.StartsWith(AssetPathPrefix, StringComparison.OrdinalIgnoreCase);

    /// <summary>是否為本專案 Release 頁面（清單或單一版本頁）</summary>
    public static bool IsTrustedReleasePageUrl(string? url) =>
        TryParseTrusted(url, out Uri? uri) &&
        (uri.AbsolutePath.Equals(ReleasesPath, StringComparison.OrdinalIgnoreCase) ||
         uri.AbsolutePath.StartsWith(ReleasesPath + "/", StringComparison.OrdinalIgnoreCase));

    /// <summary>HTTPS、github.com、預設埠且不含使用者資訊</summary>
    private static bool TryParseTrusted(string? url, [NotNullWhen(true)] out Uri? uri) =>
        TrustedHostPolicy.TryCreate(url, TrustedHosts, out uri);
}
