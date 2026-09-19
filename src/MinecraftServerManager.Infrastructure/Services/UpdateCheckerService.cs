using System.Text.Json;
using MinecraftServerManager.Core;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>
/// 應用程式執行期與環境相依探測契約介面
/// </summary>
public interface IEnvironmentRuntimeInfo
{
    public bool IsNet10DesktopRuntimeInstalled();
    public bool IsCurrentProcessFrameworkDependent();
}

/// <summary>
/// 預設本機環境相依探測實作
/// </summary>
public sealed class DefaultEnvironmentRuntimeInfo : IEnvironmentRuntimeInfo
{
    public bool IsNet10DesktopRuntimeInstalled()
    {
        string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string standardPath = Path.Combine(programFiles, "dotnet", "shared", "Microsoft.WindowsDesktop.App");
        string? dotnetRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT");
        string? customPath = !string.IsNullOrWhiteSpace(dotnetRoot) ? Path.Combine(dotnetRoot, "shared", "Microsoft.WindowsDesktop.App") : null;

        return CheckRuntimeDirectory(standardPath) || (customPath is not null && CheckRuntimeDirectory(customPath));

        static bool CheckRuntimeDirectory(string path)
        {
            if (!Directory.Exists(path))
            {
                return false;
            }

            try
            {
                return Directory.EnumerateDirectories(path, "10.*").Any();
            }
            catch
            {
                return false;
            }
        }
    }

    public bool IsCurrentProcessFrameworkDependent()
    {
        string? processPath = Environment.ProcessPath;
        return !string.IsNullOrEmpty(processPath) && processPath.Contains("framework-dependent", StringComparison.OrdinalIgnoreCase);
    }
}

/// <summary>
/// GitHub Releases 應用程式更新檢查服務實作
/// </summary>
public sealed class UpdateCheckerService(
    IHttpPort httpPort,
    IEnvironmentRuntimeInfo? runtimeInfo = null) : IUpdateCheckerService
{
    private static readonly Uri LatestReleaseUri = new("https://api.github.com/repos/Colin955023/MinecraftServerManager/releases/latest");
    private readonly IEnvironmentRuntimeInfo _runtimeInfo = runtimeInfo ?? new DefaultEnvironmentRuntimeInfo();

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

            using var doc = JsonDocument.Parse(json);
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

                    if (string.IsNullOrWhiteSpace(assetName) || string.IsNullOrWhiteSpace(assetDownload))
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

            bool hasNet10Runtime = _runtimeInfo.IsNet10DesktopRuntimeInstalled();
            bool isRunningFrameworkDependent = _runtimeInfo.IsCurrentProcessFrameworkDependent();

            var (Name, Url) = exeAssets.FirstOrDefault(a => a.Name.Contains("self-contained", StringComparison.OrdinalIgnoreCase));
            var fdCandidate = exeAssets.FirstOrDefault(a => a.Name.Contains("framework-dependent", StringComparison.OrdinalIgnoreCase));

            if (isRunningFrameworkDependent && hasNet10Runtime && !string.IsNullOrEmpty(fdCandidate.Name))
            {
                // 當前為 framework-dependent 且具備 .NET 10 Runtime 優先選用 framework-dependent
                selectedExeName = fdCandidate.Name;
                downloadUrl = fdCandidate.Url;
            }
            else if (!string.IsNullOrEmpty(Name))
            {
                // 預設與最高相容性：自包含版 (self-contained) 開箱即用
                selectedExeName = Name;
                downloadUrl = Url;
            }
            else if (!string.IsNullOrEmpty(fdCandidate.Name))
            {
                // 僅有 framework-dependent 之處理
                if (hasNet10Runtime)
                {
                    selectedExeName = fdCandidate.Name;
                    downloadUrl = fdCandidate.Url;
                }
                else
                {
                    // 缺少 .NET 10 Desktop Runtime 時禁止直接下載 framework-dependent 以防啟動失敗
                    downloadUrl = null;
                    body = "【重要提示】最新發布僅提供框架相依版 (framework-dependent)，但本機尚未安裝 .NET 10 Desktop Runtime\r\n請至發布頁面安裝相關執行環境後手動下載\r\n\r\n" + body;
                }
            }
            else if (exeAssets.Count > 0)
            {
                selectedExeName = exeAssets[0].Name;
                downloadUrl = exeAssets[0].Url;
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
