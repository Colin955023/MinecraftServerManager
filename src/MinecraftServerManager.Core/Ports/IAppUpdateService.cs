namespace MinecraftServerManager.Core.Ports;

/// <summary>應用程式更新安裝服務契約介面</summary>
public interface IAppUpdateService
{
    /// <summary>下載並驗證最新版本更新檔，回傳已通過安全驗證的更新檔本機絕對路徑</summary>
    /// <param name="update">檢查更新結果資訊</param>
    /// <param name="progress">下載與驗證進度回報（百分比 0～100、狀態訊息）</param>
    /// <param name="cancellationToken">取消權杖</param>
    /// <returns>安全下載並驗證通過的更新檔路徑</returns>
    public Task<string> DownloadAndVerifyUpdateAsync(
        UpdateCheckResult update,
        IProgress<(int Percentage, string StatusMessage)>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>安全置換執行檔並啟動新版；置換或啟動失敗時還原舊版</summary>
    /// <param name="verifiedInstallerPath">已驗證的更新檔案路徑</param>
    /// <param name="launchReplacement">包裝啟動動作（如先釋放單一執行個體鎖、失敗時取回）</param>
    public void ApplyUpdateAndRestart(string verifiedInstallerPath, Action<Action> launchReplacement);

    /// <summary>清理前次更新留下的 .old 備份檔</summary>
    public void CleanupPreviousUpdateBackup();
}
