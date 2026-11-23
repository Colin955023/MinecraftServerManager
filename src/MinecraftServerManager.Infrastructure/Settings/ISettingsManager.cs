namespace MinecraftServerManager.Infrastructure.Settings;

/// <summary>使用者設定存取契約；寫入成功才更新記憶體值</summary>
public interface ISettingsManager
{
    public string GetServersRoot();

    public void SetServersRoot(string? path);

    public void SetExactServersRoot(string? path);

    /// <summary>取得已驗證的伺服器主資料夾；不存在且 <paramref name="create"/> 為 false 時擲回 ConfigurationException</summary>
    public string GetValidatedServersRootPath(bool create = false);

    public bool IsAutoUpdateEnabled();

    public bool IsAutoBackupBeforeStartEnabled();

    public int GetBackupRetentionCount();

    public MainWindowSettings GetMainWindowSettings();

    public void SetMainWindowSettings(int width, int height, int? x = null, int? y = null, bool maximized = false);

    public string GetThemeMode();

    public string? GetCustomAccentColor();

    /// <summary>一次寫入偏好設定頁全部欄位</summary>
    public void SetPreferences(UserPreferences preferences);
}
