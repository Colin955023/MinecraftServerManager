using System.Text.Json.Serialization;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>GitHub Releases 應用程式更新檢查服務實作</summary>
public sealed class UpdateCheckerService(IHttpPort httpPort) : IUpdateCheckerService
{
    private static readonly Uri LatestReleaseUri = BuildLatestReleaseUri();
    private const string TrustedAssetHost = "github.com";
    private static readonly string TrustedAssetPathPrefix = BuildTrustedAssetPathPrefix();

    private static string RepositoryPath => new Uri(AppInfo.RepositoryUrl).AbsolutePath.Trim('/');

    private static Uri BuildLatestReleaseUri() =>
        new($"https://api.github.com/repos/{RepositoryPath}/releases/latest");

    private static string BuildTrustedAssetPathPrefix() =>
        $"/{RepositoryPath}/releases/download/";

    /// <summary>更新資產僅接受本專案 GitHub Release 的 HTTPS 下載位址，避免遭竄改的 API 回應導向其他來源</summary>
    private static bool IsTrustedAssetUrl(string url) =>
        Uri.TryCreate(url, UriKind.Absolute, out Uri? uri)
        && uri.Scheme == Uri.UriSchemeHttps
        && string.Equals(uri.Host, TrustedAssetHost, StringComparison.OrdinalIgnoreCase)
        && uri.AbsolutePath.StartsWith(TrustedAssetPathPrefix, StringComparison.Ordinal);

    public async Task<UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default)
    {
        string currentVersionStr = AppInfo.Version;
        string defaultPageUrl = AppInfo.RepositoryUrl + "/releases";

        UpdateCheckResult Unavailable(string title, string notes) => new(
            HasUpdate: false,
            CurrentVersion: currentVersionStr,
            LatestVersion: currentVersionStr,
            ReleaseTitle: title,
            ReleaseNotes: notes,
            DownloadUrl: null,
            Sha256ChecksumUrl: null,
            ReleasePageUrl: defaultPageUrl);

        try
        {
            string? json = await httpPort.GetTextAsync(LatestReleaseUri, cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                return Unavailable("無法取得更新資訊", "未能自 GitHub 取得 Release 資料");
            }

            if (JsonCodec.Deserialize<GitHubReleasePayload>(json) is not { } release)
            {
                return Unavailable("無法解析更新資訊", "GitHub Release 資料格式無效");
            }

            string tagName = release.TagName ?? "";
            bool hasUpdate = VersionValue.TryParse(tagName, out var latestVer) &&
                VersionValue.TryParse(currentVersionStr, out var currentVer) &&
                latestVer > currentVer;

            // 僅接受可信來源的附件：標準單一執行檔 MinecraftServerManager.exe 與其精準配對的 .sha256
            List<GitHubReleaseAsset> assets = release.Assets ?? [];
            string? FindTrustedAssetUrl(string name) => assets
                .FirstOrDefault(a => string.Equals(a.Name, name, StringComparison.OrdinalIgnoreCase)
                    && !string.IsNullOrWhiteSpace(a.BrowserDownloadUrl)
                    && IsTrustedAssetUrl(a.BrowserDownloadUrl))
                ?.BrowserDownloadUrl;

            string? downloadUrl = FindTrustedAssetUrl("MinecraftServerManager.exe");
            string? checksumUrl = downloadUrl is null ? null : FindTrustedAssetUrl("MinecraftServerManager.exe.sha256");

            return new UpdateCheckResult(
                HasUpdate: hasUpdate,
                CurrentVersion: currentVersionStr,
                LatestVersion: tagName,
                ReleaseTitle: release.Name ?? tagName,
                ReleaseNotes: release.Body ?? "",
                DownloadUrl: downloadUrl,
                Sha256ChecksumUrl: checksumUrl,
                ReleasePageUrl: release.HtmlUrl ?? defaultPageUrl);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            return Unavailable("檢查更新時發生例外", ex.Message);
        }
    }
}

/// <summary>GitHub 最新 Release 回應中本服務使用的欄位</summary>
internal sealed record GitHubReleasePayload(
    [property: JsonPropertyName("tag_name")] string? TagName,
    [property: JsonPropertyName("name")] string? Name,
    [property: JsonPropertyName("body")] string? Body,
    [property: JsonPropertyName("html_url")] string? HtmlUrl,
    [property: JsonPropertyName("assets")] List<GitHubReleaseAsset>? Assets);

/// <summary>GitHub Release 附件</summary>
internal sealed record GitHubReleaseAsset(
    [property: JsonPropertyName("name")] string? Name,
    [property: JsonPropertyName("browser_download_url")] string? BrowserDownloadUrl);
