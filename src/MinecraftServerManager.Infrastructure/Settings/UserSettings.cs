using System.Text.Json.Serialization;

namespace MinecraftServerManager.Infrastructure.Settings;

public sealed record MainWindowSettings(
    [property: JsonPropertyName("width")] int Width = 1350,
    [property: JsonPropertyName("height")] int Height = 820,
    [property: JsonPropertyName("x")] int? X = null,
    [property: JsonPropertyName("y")] int? Y = null,
    [property: JsonPropertyName("maximized")] bool Maximized = false);

public sealed record WindowPreferences(
    [property: JsonPropertyName("remember_size_position")] bool RememberSizePosition = true,
    [property: JsonPropertyName("main_window")] MainWindowSettings MainWindow = null!,
    [property: JsonPropertyName("auto_center")] bool AutoCenter = true,
    [property: JsonPropertyName("theme_mode")] string ThemeMode = "system")
{
    public WindowPreferences()
        : this(true, new MainWindowSettings(), true, "system")
    {
    }
}

public sealed record UserSettings(
    [property: JsonPropertyName("servers_root")] string ServersRoot = "",
    [property: JsonPropertyName("auto_update_enabled")] bool AutoUpdateEnabled = true,
    [property: JsonPropertyName("first_run_completed")] bool FirstRunCompleted = false,
    [property: JsonPropertyName("window_preferences")] WindowPreferences WindowPreferences = null!)
{
    public UserSettings()
        : this("", true, false, new WindowPreferences())
    {
    }
}
