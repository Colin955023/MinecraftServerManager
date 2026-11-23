using System.Text.Json.Serialization;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>GitHub Releases 應用程式更新檢查服務實作</summary>
public sealed class UpdateCheckerService : IUpdateCheckerService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(UpdateCheckerService));

    private readonly IHttpPort _httpPort;

    public UpdateCheckerService(IHttpPort httpPort)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        _httpPort = httpPort;
    }

    public async Task<UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default)
    {
        string currentVersionStr = AppInfo.Version;
        string defaultPageUrl = GitHubReleaseTrustPolicy.DefaultReleasePageUrl;

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
            string? json = await _httpPort.GetTextAsync(GitHubReleaseTrustPolicy.LatestReleaseUri, cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                return Unavailable("無法取得更新資訊", "未能自 GitHub 取得 Release 資料");
            }

            if (JsonCodec.Deserialize<GitHubReleasePayload>(json) is not { } release)
            {
                return Unavailable("無法解析更新資訊", "GitHub Release 資料格式無效");
            }

            string tagName = release.TagName ?? string.Empty;
            bool hasUpdate = VersionValue.TryParse(tagName, out var latestVer) &&
                VersionValue.TryParse(currentVersionStr, out var currentVer) &&
                latestVer > currentVer;

            // 只接受 MinecraftServerManager.exe 與其 .sha256
            List<GitHubReleaseAsset> assets = release.Assets ?? [];
            string? FindTrustedAssetUrl(string name) => assets
                .FirstOrDefault(a => string.Equals(a.Name, name, StringComparison.OrdinalIgnoreCase)
                    && !string.IsNullOrWhiteSpace(a.BrowserDownloadUrl)
                    && GitHubReleaseTrustPolicy.IsTrustedAssetUrl(a.BrowserDownloadUrl))
                ?.BrowserDownloadUrl;

            string? downloadUrl = FindTrustedAssetUrl("MinecraftServerManager.exe");
            string? checksumUrl = downloadUrl is null ? null : FindTrustedAssetUrl("MinecraftServerManager.exe.sha256");

            return new UpdateCheckResult(
                HasUpdate: hasUpdate,
                CurrentVersion: currentVersionStr,
                LatestVersion: tagName,
                ReleaseTitle: release.Name ?? tagName,
                ReleaseNotes: release.Body ?? string.Empty,
                DownloadUrl: downloadUrl,
                Sha256ChecksumUrl: checksumUrl,
                // 頁面連結會交給瀏覽器開啟，非官方 Release 頁一律改用預設頁
                ReleasePageUrl: GitHubReleaseTrustPolicy.IsTrustedReleasePageUrl(release.HtmlUrl) ? release.HtmlUrl! : defaultPageUrl);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "檢查應用程式更新失敗");
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
