using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 應用程式日誌管理中心
/// </summary>
public static class AppLogging
{
    private static readonly object SyncRoot = new();
    private static ILoggerFactory? _loggerFactory;
    private static RotatingFileLoggerProvider? _fileLoggerProvider;
    private static LoggerExternalScopeProvider? _scopeProvider;

    /// <summary>
    /// 初始化應用程式日誌管道
    /// </summary>
    public static void Initialize(RotatingFileLoggerOptions? options = null)
    {
        lock (SyncRoot)
        {
            if (_loggerFactory is not null)
            {
                return;
            }

            options ??= new RotatingFileLoggerOptions();

            _scopeProvider = new LoggerExternalScopeProvider();
            _fileLoggerProvider = new RotatingFileLoggerProvider(options);
            _fileLoggerProvider.SetScopeProvider(_scopeProvider);

            _loggerFactory = LoggerFactory.Create(builder =>
            {
                builder.SetMinimumLevel(options.MinimumLevel);
                builder.AddProvider(_fileLoggerProvider);
            });
        }
    }

    /// <summary>
    /// 取得指定類別名稱之 ILogger
    /// </summary>
    public static ILogger CreateLogger(string categoryName)
    {
        EnsureInitialized();
        return _loggerFactory!.CreateLogger(categoryName);
    }

    /// <summary>
    /// 取得指定泛型型別之 ILogger
    /// </summary>
    public static ILogger<T> CreateLogger<T>()
    {
        EnsureInitialized();
        return _loggerFactory!.CreateLogger<T>();
    }

    /// <summary>
    /// 取得已綁定 component 之 ComponentLogger
    /// </summary>
    public static ComponentLogger CreateComponentLogger(string componentName)
    {
        var logger = CreateLogger(componentName);
        return new ComponentLogger(logger).Bind("component", componentName);
    }

    /// <summary>
    /// 關閉並清除日誌管道，確保檔案串流完成寫入與釋放
    /// </summary>
    public static void Shutdown()
    {
        lock (SyncRoot)
        {
            try
            {
                _loggerFactory?.Dispose();
                _fileLoggerProvider?.Dispose();
            }
            finally
            {
                _loggerFactory = null;
                _fileLoggerProvider = null;
                _scopeProvider = null;
            }
        }
    }

    private static void EnsureInitialized()
    {
        if (_loggerFactory is null)
        {
            lock (SyncRoot)
            {
                if (_loggerFactory is null)
                {
                    Initialize();
                }
            }
        }
    }
}
