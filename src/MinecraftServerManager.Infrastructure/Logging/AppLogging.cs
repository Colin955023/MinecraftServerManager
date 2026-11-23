using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>應用程式記錄管理中心</summary>
public static class AppLogging
{
    private static readonly Lock SyncRoot = new();
    private static RotatingFileLoggerProvider? s_fileLoggerProvider;
    private static bool s_isInitializing;
    private static bool s_isShutdown;

    /// <summary>初始化應用程式記錄管線；已關閉後不再重新建立</summary>
    public static void Initialize()
    {
        lock (SyncRoot)
        {
            InitializeLocked();
        }
    }

    /// <summary>排清並關閉記錄管線，釋放記錄檔鎖定；之後的記錄一律略過</summary>
    public static void Shutdown()
    {
        RotatingFileLoggerProvider? provider;
        lock (SyncRoot)
        {
            if (s_isShutdown)
            {
                return;
            }

            s_isShutdown = true;
            provider = s_fileLoggerProvider;
            s_fileLoggerProvider = null;
        }

        provider?.Dispose();
    }

    /// <summary>取得指定類別名稱之 ILogger；實際記錄器於第一次使用時才解析，避免與靜態建構子互鎖</summary>
    public static ILogger CreateLogger(string categoryName)
    {
        ArgumentNullException.ThrowIfNull(categoryName);
        return new DeferredLogger(categoryName);
    }

    /// <summary>取得已繫結 component 之 ComponentLogger</summary>
    public static ComponentLogger CreateComponentLogger(string componentName) =>
        new(CreateLogger(componentName));

    /// <summary>目前寫入中的記錄檔完整路徑；記錄管線未初始化時為 null</summary>
    public static string? CurrentLogFilePath
    {
        get
        {
            lock (SyncRoot)
            {
                string? path = s_fileLoggerProvider?.CurrentFilePath;
                return string.IsNullOrEmpty(path) ? null : path;
            }
        }
    }

    /// <summary>解析實際記錄器；初始化中（重入）或已關閉時回傳 null</summary>
    private static ILogger? TryResolveLogger(string categoryName)
    {
        if (Volatile.Read(ref s_isShutdown))
        {
            return null;
        }

        lock (SyncRoot)
        {
            InitializeLocked();
            return s_fileLoggerProvider?.CreateLogger(categoryName);
        }
    }

    private static void InitializeLocked()
    {
        if (s_fileLoggerProvider is not null || s_isInitializing || s_isShutdown)
        {
            return;
        }

        s_isInitializing = true;
        try
        {
            s_fileLoggerProvider = new RotatingFileLoggerProvider(new RotatingFileLoggerOptions());
        }
        finally
        {
            s_isInitializing = false;
        }
    }

    /// <summary>延遲解析之記錄器代理</summary>
    private sealed class DeferredLogger(string categoryName) : ILogger
    {
        private ILogger? _inner;
        private bool _isShutdown;

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => Resolve()?.IsEnabled(logLevel) ?? false;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
            Resolve()?.Log(logLevel, eventId, state, exception, formatter);

        private ILogger? Resolve()
        {
            if (_isShutdown)
            {
                return null;
            }

            if (Volatile.Read(ref _inner) is { } inner)
            {
                return inner;
            }

            if (Volatile.Read(ref s_isShutdown))
            {
                _isShutdown = true;
                return null;
            }

            // 初始化中解析失敗不快取，下次呼叫再嘗試
            ILogger? resolved = TryResolveLogger(categoryName);
            if (resolved is not null)
            {
                Volatile.Write(ref _inner, resolved);
            }
            else if (Volatile.Read(ref s_isShutdown))
            {
                _isShutdown = true;
            }

            return resolved;
        }
    }
}
