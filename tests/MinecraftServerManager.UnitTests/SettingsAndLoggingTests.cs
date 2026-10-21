using Microsoft.Extensions.Logging;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

[Collection("EnvironmentVariableCollection")]
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

    [Fact]
    public void IsDevelopmentEnvironmentAccuratelyDetectsSingleFileOrDev()
    {
        string? originalEnv = Environment.GetEnvironmentVariable("MSM_DEBUG_LOG");
        object? originalAppContext = AppContext.GetData("APP_CONTEXT_PUBLISH_SINGLE_FILE");

        try
        {
            // 1. 一般測試執行階段（非 single file bundle），無環境變數覆寫
            Environment.SetEnvironmentVariable("MSM_DEBUG_LOG", null);
            AppContext.SetData("APP_CONTEXT_PUBLISH_SINGLE_FILE", null);

            // 單元測試時 EntryAssembly 非空，無 single-file 旗標，應為開發環境
            bool isDev = RuntimePaths.IsDevelopmentEnvironment();
            Assert.True(isDev);

            // 2. 當環境變數設定 MSM_DEBUG_LOG=1 時，一律為 true
            Environment.SetEnvironmentVariable("MSM_DEBUG_LOG", "1");
            Assert.True(RuntimePaths.IsDevelopmentEnvironment());

            // 3. 模擬發布之 Single-File EXE（微軟 Host 注入旗標，測試布林值與字串型態）
            Environment.SetEnvironmentVariable("MSM_DEBUG_LOG", null);
            AppContext.SetData("APP_CONTEXT_PUBLISH_SINGLE_FILE", true);
            Assert.False(RuntimePaths.IsDevelopmentEnvironment());

            AppContext.SetData("APP_CONTEXT_PUBLISH_SINGLE_FILE", "true");
            Assert.False(RuntimePaths.IsDevelopmentEnvironment());
        }
        finally
        {
            Environment.SetEnvironmentVariable("MSM_DEBUG_LOG", originalEnv);
            AppContext.SetData("APP_CONTEXT_PUBLISH_SINGLE_FILE", originalAppContext);
        }
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
                    .Where(static pair => !string.Equals(pair.Key, "{OriginalFormat}", StringComparison.Ordinal))
                    .Select(static pair => pair.Value)
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
