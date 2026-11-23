using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>以正式 <see cref="SettingsManager.SetPreferences"/> 路徑調整單一偏好</summary>
internal static class SettingsManagerTestExtensions
{
    public static void UpdatePreferences(this SettingsManager settings, Func<UserPreferences, UserPreferences> change)
    {
        var current = new UserPreferences(
            settings.IsAutoUpdateEnabled(),
            settings.IsAutoBackupBeforeStartEnabled(),
            settings.GetBackupRetentionCount(),
            settings.GetThemeMode(),
            settings.GetCustomAccentColor());
        settings.SetPreferences(change(current));
    }
}
