using Microsoft.Win32;

namespace MinecraftServerManager.Infrastructure.Settings;

/// <summary>
/// 系統主題偵測服務
/// </summary>
public static class SystemThemeService
{
    private const string PersonalizeKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize";
    private const string AppsUseLightThemeValue = "AppsUseLightTheme";

    /// <summary>
    /// 偵測 Windows 系統目前是否設定為淺色主題
    /// </summary>
    public static bool IsSystemLightTheme()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(PersonalizeKeyPath);
            if (key?.GetValue(AppsUseLightThemeValue) is int value)
            {
                return value != 0;
            }
        }
        catch
        {
        }

        return false;
    }
}
