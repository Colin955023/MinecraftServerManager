using System.Collections.Frozen;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Settings;

public sealed class SettingsManager : ISettingsManager
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SettingsManager));

    private static readonly FrozenSet<string> ValidThemeModes = FrozenSet.Create(StringComparer.Ordinal, "system", "light", "dark");
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
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException)
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

    public void SetServersRoot(string? path) => ApplyServersRoot(path, NormalizeServersRootPath(path));

    public void SetExactServersRoot(string? path) => ApplyServersRoot(path, NormalizeExactServersRootPath(path));

    /// <summary>非空輸入卻無法正規化時拒絕，避免無效路徑被靜默清空；有效路徑先確認可建立再寫入</summary>
    private void ApplyServersRoot(string? input, string normalized)
    {
        if (string.IsNullOrEmpty(normalized))
        {
            if (!string.IsNullOrWhiteSpace(input))
            {
                throw new ArgumentException($"伺服器資料夾路徑無效： {input}", nameof(input));
            }
        }
        else
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

    public bool IsAutoBackupBeforeStartEnabled()
    {
        lock (_syncRoot)
        {
            return _settings.AutoBackupBeforeStart;
        }
    }

    public int GetBackupRetentionCount()
    {
        lock (_syncRoot)
        {
            return _settings.BackupRetentionCount;
        }
    }

    private WindowPreferences GetWindowPreferences()
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

    public string? GetCustomAccentColor() => GetWindowPreferences().CustomAccentColor;

    public void SetPreferences(UserPreferences preferences)
    {
        ArgumentNullException.ThrowIfNull(preferences);
        Update(settings => settings with
        {
            AutoUpdateEnabled = preferences.AutoUpdateEnabled,
            AutoBackupBeforeStart = preferences.AutoBackupBeforeStart,
            BackupRetentionCount = preferences.BackupRetentionCount,
            WindowPreferences = NormalizeWindowPreferences(settings.WindowPreferences) with
            {
                ThemeMode = NormalizeThemeMode(preferences.ThemeMode),
                CustomAccentColor = NormalizeAccentColor(preferences.CustomAccentColor),
            },
        });
    }

    private static WindowPreferences NormalizeWindowPreferences(WindowPreferences? preferences)
    {
        preferences ??= new WindowPreferences();
        var mainWindow = preferences.MainWindow ?? new MainWindowSettings();
        return preferences with
        {
            ThemeMode = NormalizeThemeMode(preferences.ThemeMode),
            MainWindow = mainWindow,
            CustomAccentColor = NormalizeAccentColor(preferences.CustomAccentColor),
        };
    }

    /// <summary>只接受 6 位十六進位色碼並統一為 #RRGGBB；其他值視為未自訂</summary>
    private static string? NormalizeAccentColor(string? hex)
    {
        if (string.IsNullOrWhiteSpace(hex))
        {
            return null;
        }

        ReadOnlySpan<char> digits = hex.AsSpan().Trim();
        if (digits.StartsWith('#'))
        {
            digits = digits[1..];
        }

        return HashCalculator.IsHexDigest(digits, 6)
            ? string.Concat("#", digits.ToString().ToUpperInvariant())
            : null;
    }

    private UserSettings LoadSettings()
    {
        byte[]? bytes;
        try
        {
            bytes = SafeFileSystem.ReadRegularFile(_settingsPath, JsonCodec.DefaultMaxBytes);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 暫時性讀取失敗（鎖定、權限、過大）：不覆寫原檔，本次以記憶體預設值執行
            Logger.Warning(ex, "讀取設定檔失敗，本次改用預設值且不覆寫原檔: {Path}", _settingsPath);
            return new UserSettings();
        }

        UserSettings? loaded = bytes is null ? null : JsonCodec.Deserialize<UserSettings>(bytes);
        if (loaded is null)
        {
            // 檔案不存在直接寫入預設值；內容損毀須先成功備份為 .bad 才可覆寫
            var defaults = new UserSettings();
            if (bytes is null || PreserveUnreadableSettings())
            {
                TrySave(defaults, "無法寫入預設設定檔: {Path}");
            }

            return defaults;
        }

        var normalized = NormalizeSettings(loaded);
        if (loaded != normalized)
        {
            TrySave(normalized, "無法回寫正規化後的設定檔: {Path}");
        }

        return normalized;
    }

    /// <summary>將損毀的設定檔備份為 .bad；失敗回傳 false，呼叫端不得覆寫原檔</summary>
    private bool PreserveUnreadableSettings()
    {
        if (!SafeFileSystem.TryPreserveCorruptFile(_settingsPath, Logger))
        {
            return false;
        }

        Logger.Warning("設定檔無法解析，已備份為 {Path}.bad 並改用預設值", _settingsPath);
        return true;
    }

    /// <summary>啟動期間寫入失敗不應使啟動失敗；記錄後以記憶體中的值繼續</summary>
    private void TrySave(UserSettings settings, string failureMessage)
    {
        try
        {
            Save(settings);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, failureMessage, _settingsPath);
        }
    }

    /// <summary>先寫入成功才更新記憶體，避免寫檔失敗時記憶體與磁碟不一致</summary>
    private void Update(Func<UserSettings, UserSettings> update)
    {
        lock (_syncRoot)
        {
            var updated = NormalizeSettings(update(_settings));
            Save(updated);
            _settings = updated;
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
            BackupRetentionCount = NormalizeBackupRetentionCount(settings.BackupRetentionCount),
        };
    }

    private static int NormalizeBackupRetentionCount(int count) =>
        count < ServerDefaults.MinBackupRetentionCount
            ? ServerDefaults.DefaultBackupRetentionCount
            : Math.Min(count, ServerDefaults.MaxBackupRetentionCount);

    private static string NormalizeThemeMode(string? mode)
    {
        string normalized = (mode ?? "system").Trim().ToLowerInvariant();
        return ValidThemeModes.Contains(normalized) ? normalized : "system";
    }

}
