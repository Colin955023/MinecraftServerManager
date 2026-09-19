namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 應用程式更新檢查結果
/// </summary>
public sealed record UpdateCheckResult(
    bool HasUpdate,
    string CurrentVersion,
    string LatestVersion,
    string ReleaseTitle,
    string ReleaseNotes,
    string? DownloadUrl,
    string? Sha256ChecksumUrl,
    string ReleasePageUrl);

/// <summary>
/// 應用程式更新檢查服務契約介面
/// </summary>
public interface IUpdateCheckerService
{
    /// <summary>
    /// 非同步檢查 GitHub Releases 最新版本
    /// </summary>
    public Task<UpdateCheckResult> CheckForUpdateAsync(CancellationToken cancellationToken = default);
}
