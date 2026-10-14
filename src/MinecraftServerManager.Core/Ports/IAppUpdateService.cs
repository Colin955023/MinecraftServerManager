namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 應用程式更新安裝服務契約介面
/// </summary>
public interface IAppUpdateService
{
    /// <summary>
    /// 下載並驗證最新版本更新檔，回傳已通過安全驗證的更新檔本機絕對路徑。
    /// </summary>
    /// <param name="update">檢查更新結果資訊</param>
    /// <param name="progress">下載與驗證進度回報 (百分比 0~100, 狀態訊息)</param>
    /// <param name="cancellationToken">取消權杖</param>
    /// <returns>安全下載並校驗通過的更新檔路徑</returns>
    public Task<string> DownloadAndVerifyUpdateAsync(
        UpdateCheckResult update,
        IProgress<(int Percentage, string StatusMessage)>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 套用更新並重新啟動主程式（安全置換執行檔並喚醒新版進程）。
    /// </summary>
    /// <param name="verifiedInstallerPath">已驗證的更新檔案路徑</param>
    public void ApplyUpdateAndRestart(string verifiedInstallerPath);
}
