using System.Text.Json;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Settings;

public sealed class SettingsManager
{
    private const string UserDataEnvironmentVariable = "MSM_USER_DATA_DIR";
    private static readonly string[] ValidThemeModes = ["system", "light", "dark"];
    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly Lock _syncRoot = new();
    private readonly string _settingsPath;
    private UserSettings _settings;

    public SettingsManager(string? userDataDirectory = null)
    {
        string resolvedUserDataDirectory = ResolveUserDataDirectory(userDataDirectory);
        _settingsPath = Path.Combine(resolvedUserDataDirectory, "user_settings.json");
        _settings = LoadSettings();
    }

    public string SettingsPath => _settingsPath;

    public UserSettings Snapshot
    {
        get
        {
            lock (_syncRoot)
            {
                return _settings;
            }
        }
    }

    public static string NormalizeServersRootPath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return string.Empty;
        }

        try
        {
            string resolved = Path.GetFullPath(path.Trim());
            if (!string.Equals(Path.GetFileName(resolved), "servers", StringComparison.OrdinalIgnoreCase))
            {
                resolved = Path.Combine(resolved, "servers");
            }

            return Path.TrimEndingDirectorySeparator(Path.GetFullPath(resolved));
        }
        catch (ArgumentException)
        {
            return string.Empty;
        }
        catch (NotSupportedException)
        {
            return string.Empty;
        }
    }

    public static string NormalizeServersBaseDirectory(string? path)
    {
        string root = NormalizeServersRootPath(path);
        if (string.IsNullOrEmpty(root))
        {
            return string.Empty;
        }

        return Directory.GetParent(root)?.FullName ?? root;
    }

    public static string BuildServersRootPath(string baseDirectory)
    {
        ArgumentException.ThrowIfNullOrEmpty(baseDirectory);
        return NormalizeServersRootPath(baseDirectory);
    }

    public string GetServersRoot()
    {
        lock (_syncRoot)
        {
            return _settings.ServersRoot.Trim();
        }
    }

    public void SetServersRoot(string? path)
    {
        string normalized = NormalizeServersRootPath(path);
        if (!string.IsNullOrEmpty(normalized))
        {
            SafeFileSystem.ResolveStableDirectory(normalized, create: true);
        }
        Update(settings => settings with { ServersRoot = normalized });
    }

    public string GetValidatedServersRootPath(bool create = false)
    {
        string serversRoot = GetServersRoot();
        if (string.IsNullOrEmpty(serversRoot))
        {
            throw new ConfigurationException("尚未設定伺服器主資料夾");
        }

        serversRoot = NormalizeServersRootPath(serversRoot);
        if (File.Exists(serversRoot))
        {
            throw new ConfigurationException($"伺服器資料夾路徑無效： {serversRoot}");
        }

        if (!Directory.Exists(serversRoot) && !create)
        {
            throw new ConfigurationException($"找不到伺服器資料夾： {serversRoot}");
        }

        try
        {
            return SafeFileSystem.ResolveStableDirectory(serversRoot, create);
        }
        catch (DirectoryNotFoundException exception)
        {
            throw new ConfigurationException($"找不到伺服器資料夾： {serversRoot}", exception);
        }
        catch (SafeFileSystemException exception)
        {
            throw new ConfigurationException($"伺服器資料夾路徑無效： {serversRoot}", exception);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new ConfigurationException($"無法建立伺服器資料夾： {serversRoot}", exception);
        }
    }

    public bool IsAutoUpdateEnabled()
    {
        lock (_syncRoot)
        {
            return _settings.AutoUpdateEnabled;
        }
    }

    public void SetAutoUpdateEnabled(bool enabled) => Update(settings => settings with { AutoUpdateEnabled = enabled });

    public bool IsFirstRunCompleted()
    {
        lock (_syncRoot)
        {
            return _settings.FirstRunCompleted;
        }
    }

    public void MarkFirstRunCompleted() => Update(settings => settings with { FirstRunCompleted = true });

    /// <summary>
    /// 全域 UI 縮放比例（0.5 ~ 3.0，預設 1.0）
    /// </summary>
    public double GetUiScale()
    {
        lock (_syncRoot)
        {
            return NormalizeUiScale(_settings.UiScale);
        }
    }

    public void SetUiScale(double scale) => Update(settings => settings with { UiScale = NormalizeUiScale(scale) });

    private static double NormalizeUiScale(double scale)
    {
        if (double.IsNaN(scale) || double.IsInfinity(scale) || scale <= 0)
        {
            return 1.0;
        }

        return Math.Clamp(Math.Round(scale, 2), 0.5, 3.0);
    }

    public WindowPreferences GetWindowPreferences()
    {
        lock (_syncRoot)
        {
            return NormalizeWindowPreferences(_settings.WindowPreferences);
        }
    }

    public MainWindowSettings GetMainWindowSettings() => GetWindowPreferences().MainWindow;

    public void SetMainWindowSettings(int width, int height, int? x = null, int? y = null, bool maximized = false)
    {
        UpdateWindowPreferences(preferences => preferences with
        {
            MainWindow = new MainWindowSettings(width, height, x, y, maximized),
        });
    }

    public string GetThemeMode() => GetWindowPreferences().ThemeMode;

    public void SetThemeMode(string? mode) => UpdateWindowPreferences(preferences => preferences with { ThemeMode = NormalizeThemeMode(mode) });

    private static WindowPreferences NormalizeWindowPreferences(WindowPreferences? preferences)
    {
        preferences ??= new WindowPreferences();
        var mainWindow = preferences.MainWindow ?? new MainWindowSettings();
        return preferences with
        {
            ThemeMode = NormalizeThemeMode(preferences.ThemeMode),
            MainWindow = mainWindow,
        };
    }

    private UserSettings LoadSettings()
    {
        using var result = JsonCodec.ReadJsonWithBytes(_settingsPath);
        if (result is null)
        {
            var defaults = new UserSettings();
            Save(defaults);
            return defaults;
        }

        try
        {
            var loaded = result.Document.RootElement.Deserialize<UserSettings>(ReadOptions);
            var normalized = NormalizeSettings(loaded ?? new UserSettings());
            if (loaded is not null && !string.Equals(loaded.ServersRoot, normalized.ServersRoot, StringComparison.Ordinal))
            {
                Save(normalized);
            }
            return normalized;
        }
        catch (JsonException)
        {
            return new UserSettings();
        }
    }

    private void Update(Func<UserSettings, UserSettings> update)
    {
        lock (_syncRoot)
        {
            var updated = NormalizeSettings(update(_settings));
            _settings = updated;
            Save(updated);
        }
    }

    private void UpdateWindowPreferences(Func<WindowPreferences, WindowPreferences> update) => Update(settings => settings with { WindowPreferences = update(NormalizeWindowPreferences(settings.WindowPreferences)) });

    private void Save(UserSettings settings)
    {
        if (!AtomicFileWriter.WriteJson(_settingsPath, settings, indented: true, skipIfUnchanged: true))
        {
            throw new IOException($"無法寫入設定檔： {_settingsPath}");
        }
    }

    private static UserSettings NormalizeSettings(UserSettings settings)
    {
        return settings with
        {
            ServersRoot = NormalizeServersRootPath(settings.ServersRoot).Trim(),
            WindowPreferences = NormalizeWindowPreferences(settings.WindowPreferences),
        };
    }

    private static string NormalizeThemeMode(string? mode)
    {
        string normalized = (mode ?? "system").Trim().ToLowerInvariant();
        return ValidThemeModes.Contains(normalized, StringComparer.Ordinal) ? normalized : "system";
    }

    private static string ResolveUserDataDirectory(string? userDataDirectory)
    {
        string? configured = string.IsNullOrWhiteSpace(userDataDirectory)
            ? Environment.GetEnvironmentVariable(UserDataEnvironmentVariable)
            : userDataDirectory;
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return Path.GetFullPath(configured);
        }

        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(localAppData, "Programs", "MinecraftServerManager");
    }
}
