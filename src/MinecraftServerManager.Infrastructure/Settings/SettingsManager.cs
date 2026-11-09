using System.Collections.Frozen;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Settings;

public sealed class SettingsManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SettingsManager));

    private static readonly FrozenSet<string> ValidThemeModes = FrozenSet.ToFrozenSet(["system", "light", "dark"], StringComparer.Ordinal);
    private readonly Lock _syncRoot = new();
    private readonly string _settingsPath;
    private UserSettings _settings;

    public SettingsManager(string userDataDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(userDataDirectory);
        _settingsPath = Path.Combine(Path.GetFullPath(userDataDirectory), "user_settings.json");
        _settings = LoadSettings();
    }

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

    public static string NormalizeExactServersRootPath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return string.Empty;
        }

        try
        {
            string resolved = Path.GetFullPath(path.Trim());
            return Path.TrimEndingDirectorySeparator(resolved);
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

    public static string NormalizeServersRootPath(string? path)
    {
        string resolved = NormalizeExactServersRootPath(path);
        if (string.IsNullOrEmpty(resolved))
        {
            return string.Empty;
        }

        if (!string.Equals(Path.GetFileName(resolved), "servers", StringComparison.OrdinalIgnoreCase))
        {
            resolved = Path.Combine(resolved, "servers");
        }

        return Path.TrimEndingDirectorySeparator(Path.GetFullPath(resolved));
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

    public void SetExactServersRoot(string? path)
    {
        string normalized = NormalizeExactServersRootPath(path);
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

        serversRoot = NormalizeExactServersRootPath(serversRoot);
        if (SafeFileSystem.FileExists(serversRoot))
        {
            throw new ConfigurationException($"伺服器資料夾路徑無效： {serversRoot}");
        }

        if (!SafeFileSystem.DirectoryExists(serversRoot) && !create)
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

    public string? GetCustomAccentColor() => GetWindowPreferences().CustomAccentColor;

    public void SetCustomAccentColor(string? hex) => UpdateWindowPreferences(preferences => preferences with { CustomAccentColor = string.IsNullOrWhiteSpace(hex) ? null : hex.Trim() });

    private static WindowPreferences NormalizeWindowPreferences(WindowPreferences? preferences)
    {
        preferences ??= new WindowPreferences();
        var mainWindow = preferences.MainWindow ?? new MainWindowSettings();
        return preferences with
        {
            ThemeMode = NormalizeThemeMode(preferences.ThemeMode),
            MainWindow = mainWindow,
            CustomAccentColor = string.IsNullOrWhiteSpace(preferences.CustomAccentColor) ? null : preferences.CustomAccentColor.Trim(),
        };
    }

    private UserSettings LoadSettings()
    {
        byte[]? bytes = null;
        try
        {
            bytes = SafeFileSystem.ReadRegularFile(_settingsPath, JsonCodec.DefaultMaxBytes);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "讀取設定檔失敗：{Path}", _settingsPath);
        }

        UserSettings? loaded = bytes is null ? null : JsonCodec.Deserialize<UserSettings>(bytes);
        if (loaded is null)
        {
            // 檔案存在卻讀不到（損毀、過大或被鎖定）：先保留原檔，避免預設值覆蓋使用者設定
            PreserveUnreadableSettings();
            var defaults = new UserSettings();
            TrySaveDefaults(defaults);
            return defaults;
        }

        var normalized = NormalizeSettings(loaded);
        if (loaded != normalized)
        {
            Save(normalized);
        }
        return normalized;
    }

    private void PreserveUnreadableSettings()
    {
        if (!SafeFileSystem.FileExists(_settingsPath))
        {
            return;
        }

        try
        {
            SafeFileSystem.CopyFile(_settingsPath, _settingsPath + ".bad", overwrite: true);
            Logger.Warning("設定檔無法讀取，已備份為 {Path}.bad 並改用預設值", _settingsPath);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "無法備份損毀的設定檔：{Path}", _settingsPath);
        }
    }

    private void TrySaveDefaults(UserSettings defaults)
    {
        try
        {
            Save(defaults);
        }
        catch (IOException ex)
        {
            // 寫入失敗不應使啟動失敗；使用記憶體中的預設值繼續
            Logger.Warning(ex, "無法寫入預設設定檔：{Path}", _settingsPath);
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
            ServersRoot = NormalizeExactServersRootPath(settings.ServersRoot).Trim(),
            WindowPreferences = NormalizeWindowPreferences(settings.WindowPreferences),
        };
    }

    private static string NormalizeThemeMode(string? mode)
    {
        string normalized = (mode ?? "system").Trim().ToLowerInvariant();
        return ValidThemeModes.Contains(normalized) ? normalized : "system";
    }

}
