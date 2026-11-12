using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>應用程式記錄管理中心</summary>
public static class AppLogging
{
    private static readonly Lock SyncRoot = new();
    private static RotatingFileLoggerProvider? _fileLoggerProvider;

    /// <summary>初始化應用程式記錄管線</summary>
    public static void Initialize()
    {
        lock (SyncRoot)
        {
            if (_fileLoggerProvider is not null)
            {
                return;
            }

            _fileLoggerProvider = new RotatingFileLoggerProvider(new RotatingFileLoggerOptions());
        }
    }

    /// <summary>取得指定類別名稱之 ILogger</summary>
    public static ILogger CreateLogger(string categoryName)
    {
        // 初始化檢查與建立記錄器必須在同一把鎖內完成，避免與 Shutdown 競態而使用到已釋放的工廠
        lock (SyncRoot)
        {
            EnsureInitialized();
            return _fileLoggerProvider!.CreateLogger(categoryName);
        }
    }

    /// <summary>取得已繫結 component 之 ComponentLogger</summary>
    public static ComponentLogger CreateComponentLogger(string componentName)
    {
        var logger = CreateLogger(componentName);
        return new ComponentLogger(logger);
    }

    /// <summary>目前寫入中的記錄檔完整路徑；記錄管線未初始化時為 null</summary>
    public static string? CurrentLogFilePath
    {
        get
        {
            lock (SyncRoot)
            {
                string? path = _fileLoggerProvider?.CurrentFilePath;
                return string.IsNullOrEmpty(path) ? null : path;
            }
        }
    }

    private static void EnsureInitialized()
    {
        if (_fileLoggerProvider is null)
        {
            Initialize();
        }
    }
}
