using System.Text.Json.Serialization;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Infrastructure.Settings;

public sealed record MainWindowSettings(
    [property: JsonPropertyName("width")] int Width = 1350,
    [property: JsonPropertyName("height")] int Height = 820,
    [property: JsonPropertyName("x")] int? X = null,
    [property: JsonPropertyName("y")] int? Y = null,
    [property: JsonPropertyName("maximized")] bool Maximized = false);

public sealed record WindowPreferences(
    [property: JsonPropertyName("main_window")] MainWindowSettings MainWindow = null!,
    [property: JsonPropertyName("theme_mode")] string ThemeMode = "system",
    [property: JsonPropertyName("custom_accent_color")] string? CustomAccentColor = null)
{
    public WindowPreferences()
        : this(new MainWindowSettings(), "system", null)
    {
    }
}

/// <summary>偏好設定頁可編輯欄位，供單次批次寫入</summary>
public sealed record UserPreferences(bool AutoUpdateEnabled, bool AutoBackupBeforeStart, int BackupRetentionCount, string ThemeMode, string? CustomAccentColor);

public sealed record UserSettings(
    [property: JsonPropertyName("servers_root")] string ServersRoot = "",
    [property: JsonPropertyName("auto_update_enabled")] bool AutoUpdateEnabled = true,
    [property: JsonPropertyName("window_preferences")] WindowPreferences WindowPreferences = null!,
    [property: JsonPropertyName("auto_backup_before_start")] bool AutoBackupBeforeStart = false,
    [property: JsonPropertyName("backup_retention_count")] int BackupRetentionCount = ServerDefaults.DefaultBackupRetentionCount)
{
    public UserSettings()
        : this(string.Empty, true, new WindowPreferences(), false, ServerDefaults.DefaultBackupRetentionCount)
    {
    }
}
