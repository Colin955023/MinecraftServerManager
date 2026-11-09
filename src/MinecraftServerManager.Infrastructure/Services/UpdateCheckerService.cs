using System.Text.Json;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>
/// GitHub Releases 應用程式更新檢查服務實作
/// </summary>
public sealed class UpdateCheckerService(IHttpPort httpPort) : IUpdateCheckerService
{
    private static readonly Uri LatestReleaseUri = BuildLatestReleaseUri();
    private const string TrustedAssetHost = "github.com";
    private static readonly string TrustedAssetPathPrefix = BuildTrustedAssetPathPrefix();

    private static Uri BuildLatestReleaseUri()
    {
        string repoPath = new Uri(AppInfo.RepositoryUrl).AbsolutePath.Trim('/');
        return new Uri($"https://api.github.com/repos/{repoPath}/releases/latest");
    }

    private static string BuildTrustedAssetPathPrefix()
    {
        string repoPath = new Uri(AppInfo.RepositoryUrl).AbsolutePath.Trim('/');
        return $"/{repoPath}/releases/download/";
    }

    /// <summary>
    /// 更新資產僅接受本專案 GitHub Release 的 HTTPS 下載位址，避免遭竄改的 API 回應導向其他來源
    /// </summary>
    private static bool IsTrustedAssetUrl(string url) =>
        Uri.TryCreate(url, UriKind.Absolute, out Uri? uri)
        && uri.Scheme == Uri.UriSchemeHttps
        && string.Equals(uri.Host, TrustedAssetHost, StringComparison.OrdinalIgnoreCase)
        && uri.AbsolutePath.StartsWith(TrustedAssetPathPrefix, StringComparison.Ordinal);

    public async Task<UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default)
    {
        string currentVersionStr = AppInfo.Version;
        string defaultPageUrl = AppInfo.RepositoryUrl + "/releases";

        try
        {
            string? json = await httpPort.GetTextAsync(LatestReleaseUri, cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(json))
            {
                return new UpdateCheckResult(
                    HasUpdate: false,
                    CurrentVersion: currentVersionStr,
                    LatestVersion: currentVersionStr,
                    ReleaseTitle: "無法取得更新資訊",
                    ReleaseNotes: "未能自 GitHub 取得 Release 資料",
                    DownloadUrl: null,
                    Sha256ChecksumUrl: null,
                    ReleasePageUrl: defaultPageUrl);
            }

            using var doc = JsonCodec.ParseDocument(json);
            var root = doc.RootElement;

            string tagName = root.TryGetProperty("tag_name", out var tagElem) ? tagElem.GetString() ?? "" : "";
            string title = root.TryGetProperty("name", out var nameElem) ? nameElem.GetString() ?? tagName : tagName;
            string body = root.TryGetProperty("body", out var bodyElem) ? bodyElem.GetString() ?? "" : "";
            string htmlUrl = root.TryGetProperty("html_url", out var htmlElem) ? htmlElem.GetString() ?? defaultPageUrl : defaultPageUrl;

            bool hasUpdate = false;
            if (VersionValue.TryParse(tagName, out var latestVer) &&
                VersionValue.TryParse(currentVersionStr, out var currentVer))
            {
                hasUpdate = latestVer > currentVer;
            }

            var exeAssets = new List<(string Name, string Url)>();
            var sha256Assets = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            if (root.TryGetProperty("assets", out var assetsElem) && assetsElem.ValueKind == JsonValueKind.Array)
            {
                foreach (var asset in assetsElem.EnumerateArray())
                {
                    string assetName = asset.TryGetProperty("name", out var aName) ? aName.GetString() ?? "" : "";
                    string? assetDownload = asset.TryGetProperty("browser_download_url", out var aUrl) ? aUrl.GetString() : null;

                    if (string.IsNullOrWhiteSpace(assetName) || string.IsNullOrWhiteSpace(assetDownload) || !IsTrustedAssetUrl(assetDownload))
                    {
                        continue;
                    }

                    if (assetName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                    {
                        exeAssets.Add((assetName, assetDownload));
                    }
                    else if (assetName.EndsWith(".sha256", StringComparison.OrdinalIgnoreCase))
                    {
                        sha256Assets[assetName] = assetDownload;
                    }
                }
            }

            string? selectedExeName = null;
            string? downloadUrl = null;
            string? checksumUrl = null;

            // 優先選擇標準單一執行檔 MinecraftServerManager.exe
            var (Name, Url) = exeAssets.FirstOrDefault(a => string.Equals(a.Name, "MinecraftServerManager.exe", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(Name))
            {
                selectedExeName = Name;
                downloadUrl = Url;
            }
            else
            {
                // 回退相容：若為舊版 Release 帶有 self-contained 或其他 exe
                var scCandidate = exeAssets.FirstOrDefault(a => a.Name.Contains("self-contained", StringComparison.OrdinalIgnoreCase));
                if (!string.IsNullOrEmpty(scCandidate.Name))
                {
                    selectedExeName = scCandidate.Name;
                    downloadUrl = scCandidate.Url;
                }
                else if (exeAssets.Count > 0)
                {
                    selectedExeName = exeAssets[0].Name;
                    downloadUrl = exeAssets[0].Url;
                }
            }

            // 精準 Checksum 配對
            if (!string.IsNullOrEmpty(selectedExeName))
            {
                string expectedShaName = selectedExeName + ".sha256";
                if (sha256Assets.TryGetValue(expectedShaName, out string? shaUrl))
                {
                    checksumUrl = shaUrl;
                }
            }

            return new UpdateCheckResult(
                HasUpdate: hasUpdate,
                CurrentVersion: currentVersionStr,
                LatestVersion: tagName,
                ReleaseTitle: title,
                ReleaseNotes: body,
                DownloadUrl: downloadUrl,
                Sha256ChecksumUrl: checksumUrl,
                ReleasePageUrl: htmlUrl);
        }
        catch (Exception ex)
        {
            return new UpdateCheckResult(
                HasUpdate: false,
                CurrentVersion: currentVersionStr,
                LatestVersion: currentVersionStr,
                ReleaseTitle: "檢查更新時發生例外",
                ReleaseNotes: ex.Message,
                DownloadUrl: null,
                Sha256ChecksumUrl: null,
                ReleasePageUrl: defaultPageUrl);
        }
    }
}
