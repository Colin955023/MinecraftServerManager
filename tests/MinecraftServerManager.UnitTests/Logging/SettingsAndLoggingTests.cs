using Microsoft.Extensions.Logging;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.Logging;

public sealed class SettingsAndLoggingTests
{
    [Fact]
    public void Settings_SaveAndReload_PreservesTypedValues()
    {
        using var userDataTemp = new TempDirectory("msm-settings-");
        string userData = userDataTemp.FullName;
        var settings = new SettingsManager(userData);
        settings.SetServersRoot(Path.Combine(userData, "servers"));
        settings.UpdatePreferences(p => p with { AutoUpdateEnabled = false });
        settings.UpdatePreferences(p => p with { ThemeMode = "dark" });
        settings.SetMainWindowSettings(1600, 900, 10, 20, maximized: true);

        var reloaded = new SettingsManager(userData);

        string expectedRoot = Path.Combine(Path.GetFullPath(userData), "servers");
        Assert.Equal(expectedRoot, reloaded.GetServersRoot());
        Assert.Equal(expectedRoot, reloaded.GetValidatedServersRootPath(create: true));
        Assert.False(reloaded.IsAutoUpdateEnabled());
        Assert.Equal("dark", reloaded.GetThemeMode());
        Assert.Equal(new MainWindowSettings(1600, 900, 10, 20, true), reloaded.GetMainWindowSettings());
    }

    [Fact]
    public void Settings_InvalidThemeAndMissingRoot_Normalizes()
    {
        using var userDataTemp = new TempDirectory("msm-settings-");
        string userData = userDataTemp.FullName;
        var settings = new SettingsManager(userData);
        settings.UpdatePreferences(p => p with { ThemeMode = "unknown" });
        settings.SetServersRoot(userData);

        Assert.Equal("system", settings.GetThemeMode());
        string expectedRoot = Path.Combine(Path.GetFullPath(userData), "servers");
        Assert.Equal(expectedRoot, settings.GetServersRoot());
        string serversRoot = settings.GetValidatedServersRootPath(create: true);

        Assert.True(Directory.Exists(serversRoot));
        Assert.Equal(expectedRoot, serversRoot);
    }

    [Fact]
    public void Settings_ServersRootNotConfigured_Throws()
    {
        using var userDataTemp = new TempDirectory("msm-settings-");
        string userData = userDataTemp.FullName;
        var settings = new SettingsManager(userData);

        var exception = Assert.Throws<ConfigurationException>(() => settings.GetValidatedServersRootPath());

        Assert.Equal("尚未設定伺服器主資料夾", exception.Message);
    }

    [Fact]
    public void ComponentLogger_Information_ForwardsTemplateAndArguments()
    {
        var logger = new CapturingLogger();
        var Logger = new ComponentLogger(logger);

        Logger.Information("已載入 {Count} 筆設定", 3);

        Assert.Equal(LogLevel.Information, logger.Level);
        Assert.Equal("已載入 3 筆設定", logger.Message);
        Assert.Equal(3, logger.Arguments![0]);
    }

    private sealed class CapturingLogger : ILogger
    {
        public LogLevel? Level { get; private set; }

        public string? Message { get; private set; }

        public object?[]? Arguments { get; private set; }

        public IDisposable? BeginScope<TState>(TState state)
            where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(
            LogLevel logLevel,
            EventId eventId,
            TState state,
            Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            Level = logLevel;
            Message = formatter(state, exception);
            Arguments = state is IReadOnlyList<KeyValuePair<string, object?>> values
                ? values
                    .Where(static pair => !string.Equals(pair.Key, "{OriginalFormat}", StringComparison.Ordinal))
                    .Select(static pair => pair.Value)
                    .ToArray()
                : null;
        }
    }

    [Fact]
    public void BackupSettings_SaveAndReload_KeepsDefaultsAndValues()
    {
        using var temp = new TempDirectory("msm-settings-backup-");
        var settings = new SettingsManager(temp.FullName);

        Assert.False(settings.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(10, settings.GetBackupRetentionCount());

        settings.UpdatePreferences(p => p with { AutoBackupBeforeStart = true });
        settings.UpdatePreferences(p => p with { BackupRetentionCount = 25 });

        var reloaded = new SettingsManager(temp.FullName);
        Assert.True(reloaded.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(25, reloaded.GetBackupRetentionCount());
    }

    [Fact]
    public void BackupSettings_OldSettingsFileWithoutNewFields_UsesDefaults()
    {
        using var temp = new TempDirectory("msm-settings-backup-old-");
        File.WriteAllText(Path.Combine(temp.FullName, "user_settings.json"), "{\"auto_update_enabled\":false}");

        var settings = new SettingsManager(temp.FullName);

        Assert.False(settings.IsAutoUpdateEnabled());
        Assert.False(settings.IsAutoBackupBeforeStartEnabled());
        Assert.Equal(10, settings.GetBackupRetentionCount());
    }

    [Theory]
    [InlineData(0, 10)]
    [InlineData(-5, 10)]
    [InlineData(1, 1)]
    [InlineData(100, 100)]
    [InlineData(500, 100)]
    public void BackupRetentionCount_OutOfRange_IsClamped(int input, int expected)
    {
        using var temp = new TempDirectory("msm-settings-backup-clamp-");
        var settings = new SettingsManager(temp.FullName);

        settings.UpdatePreferences(p => p with { BackupRetentionCount = input });

        Assert.Equal(expected, settings.GetBackupRetentionCount());
    }
}
