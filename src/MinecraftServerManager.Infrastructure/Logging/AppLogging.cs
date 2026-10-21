using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 應用程式記錄管理中心
/// </summary>
public static class AppLogging
{
    private static readonly Lock SyncRoot = new();
    private static RotatingFileLoggerProvider? _fileLoggerProvider;
    private static LoggerExternalScopeProvider? _scopeProvider;

    /// <summary>
    /// 初始化應用程式記錄管線
    /// </summary>
    public static void Initialize(RotatingFileLoggerOptions? options = null)
    {
        lock (SyncRoot)
        {
            if (_fileLoggerProvider is not null)
            {
                return;
            }

            options ??= new RotatingFileLoggerOptions();

            _scopeProvider = new LoggerExternalScopeProvider();
            _fileLoggerProvider = new RotatingFileLoggerProvider(options);
            _fileLoggerProvider.SetScopeProvider(_scopeProvider);
        }
    }

    /// <summary>
    /// 取得指定類別名稱之 ILogger
    /// </summary>
    public static ILogger CreateLogger(string categoryName)
    {
        // 初始化檢查與建立記錄器必須在同一把鎖內完成，避免與 Shutdown 競態而使用到已釋放的工廠
        lock (SyncRoot)
        {
            EnsureInitialized();
            return _fileLoggerProvider!.CreateLogger(categoryName);
        }
    }

    /// <summary>
    /// 取得已綁定 component 之 ComponentLogger
    /// </summary>
    public static ComponentLogger CreateComponentLogger(string componentName)
    {
        var logger = CreateLogger(componentName);
        return new ComponentLogger(logger);
    }

    /// <summary>
    /// 關閉並清除記錄管線，確保檔案串流完成寫入與釋放
    /// </summary>
    public static void Shutdown()
    {
        lock (SyncRoot)
        {
            try
            {
                _fileLoggerProvider?.Dispose();
            }
            finally
            {
                _fileLoggerProvider = null;
                _scopeProvider = null;
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
