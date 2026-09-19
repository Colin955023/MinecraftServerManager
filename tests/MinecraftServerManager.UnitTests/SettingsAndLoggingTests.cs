using Microsoft.Extensions.Logging;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class SettingsAndLoggingTests
{
    [Fact]
    public void SettingsRoundTripPreservesTypedValues()
    {
        string userData = CreateTemporaryDirectory();
        try
        {
            var settings = new SettingsManager(userData);
            settings.SetServersRoot(Path.Combine(userData, "servers"));
            settings.SetAutoUpdateEnabled(false);
            settings.MarkFirstRunCompleted();
            settings.SetThemeMode("dark");
            settings.SetMainWindowSettings(1600, 900, 10, 20, maximized: true);

            var reloaded = new SettingsManager(userData);

            string expectedRoot = Path.Combine(Path.GetFullPath(userData), "servers");
            Assert.Equal(expectedRoot, reloaded.GetServersRoot());
            Assert.Equal(expectedRoot, reloaded.GetValidatedServersRootPath(create: true));
            Assert.False(reloaded.IsAutoUpdateEnabled());
            Assert.True(reloaded.IsFirstRunCompleted());
            Assert.Equal("dark", reloaded.GetThemeMode());
            Assert.Equal(new MainWindowSettings(1600, 900, 10, 20, true), reloaded.GetMainWindowSettings());
        }
        finally
        {
            Directory.Delete(userData, recursive: true);
        }
    }

    [Fact]
    public void SettingsNormalizeInvalidThemeAndCreateServersRoot()
    {
        string userData = CreateTemporaryDirectory();
        try
        {
            var settings = new SettingsManager(userData);
            settings.SetThemeMode("unknown");
            settings.SetServersRoot(userData);

            Assert.Equal("system", settings.GetThemeMode());
            string expectedRoot = Path.Combine(Path.GetFullPath(userData), "servers");
            Assert.Equal(expectedRoot, settings.GetServersRoot());
            string serversRoot = settings.GetValidatedServersRootPath(create: true);

            Assert.True(Directory.Exists(serversRoot));
            Assert.Equal(expectedRoot, serversRoot);
        }
        finally
        {
            Directory.Delete(userData, recursive: true);
        }
    }

    [Fact]
    public void SettingsRequireConfiguredServersRoot()
    {
        string userData = CreateTemporaryDirectory();
        try
        {
            var settings = new SettingsManager(userData);

            var exception = Assert.Throws<ConfigurationException>(() => settings.GetValidatedServersRootPath());

            Assert.Equal("尚未設定伺服器主資料夾", exception.Message);
        }
        finally
        {
            Directory.Delete(userData, recursive: true);
        }
    }

    [Fact]
    public void ComponentLoggerBindsStructuredContext()
    {
        var logger = new CapturingLogger();
        var componentLogger = new ComponentLogger(logger).Bind("component", "SettingsManager");

        componentLogger.Information("已載入 {Count} 筆設定", 3);

        Assert.Equal(LogLevel.Information, logger.Level);
        Assert.Equal("已載入 3 筆設定", logger.Message);
        Assert.Equal("SettingsManager", Assert.IsType<string>(logger.Scope!["component"]));
        Assert.Equal(3, logger.Arguments![0]);
    }

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-settings-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }

    private sealed class CapturingLogger : ILogger
    {
        public LogLevel? Level { get; private set; }

        public string? Message { get; private set; }

        public object?[]? Arguments { get; private set; }

        public IReadOnlyDictionary<string, object?>? Scope { get; private set; }

        public IDisposable BeginScope<TState>(TState state)
            where TState : notnull
        {
            Scope = state as IReadOnlyDictionary<string, object?>;
            return NoopDisposable.Instance;
        }

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
                    .Where(pair => !string.Equals(pair.Key, "{OriginalFormat}", StringComparison.Ordinal))
                    .Select(pair => pair.Value)
                    .ToArray()
                : null;
        }
    }

    private sealed class NoopDisposable : IDisposable
    {
        public static NoopDisposable Instance { get; } = new();

        public void Dispose()
        {
        }
    }
}
