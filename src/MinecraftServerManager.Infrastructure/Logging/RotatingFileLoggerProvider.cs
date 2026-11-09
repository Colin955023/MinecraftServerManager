using System.Collections.Concurrent;
using System.Text;
using Microsoft.Extensions.Logging;
using MinecraftServerManager.Infrastructure.FileSystem;

using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 提供單檔上限 10 MiB 輪替與最多 10 檔保留之檔案記錄器提供者
/// </summary>
public sealed class RotatingFileLoggerProvider : ILoggerProvider, ISupportExternalScope
{
    private readonly RotatingFileLoggerOptions _options;
    private readonly Lock _syncRoot = new();
    private readonly ConcurrentDictionary<string, RotatingFileLogger> _loggers = new(StringComparer.OrdinalIgnoreCase);
    private IExternalScopeProvider? _scopeProvider;
    private StreamWriter? _writer;
    private string _currentFilePath = string.Empty;
    private long _currentFileBytes;
    private bool _isDisposed;
    private Exception? _lastFileIoException;
    private static Exception? s_lastPruneException;

    public RotatingFileLoggerProvider(RotatingFileLoggerOptions? options = null)
    {
        _options = options ?? new RotatingFileLoggerOptions();
        InitializeWriter();
    }

    internal Exception? LastFileIoException => _lastFileIoException;

    /// <summary>
    /// 目前寫入中的記錄檔完整路徑；初始化失敗時為空字串
    /// </summary>
    internal string CurrentFilePath
    {
        get
        {
            lock (_syncRoot)
            {
                return _currentFilePath;
            }
        }
    }
    internal static Exception? LastPruneException => s_lastPruneException;

    public void SetScopeProvider(IExternalScopeProvider scopeProvider) => _scopeProvider = scopeProvider;

    public ILogger CreateLogger(string categoryName)
    {
        ObjectDisposedException.ThrowIf(_isDisposed, this);
        return _loggers.GetOrAdd(categoryName, name => new RotatingFileLogger(this, name));
    }

    public void Dispose()
    {
        lock (_syncRoot)
        {
            if (_isDisposed)
            {
                return;
            }

            _isDisposed = true;
            try
            {
                _writer?.Flush();
                _writer?.Dispose();
            }
            catch (Exception ex)
            {
                _lastFileIoException = ex;
            }
            finally
            {
                _writer = null;
            }
        }
    }

    internal bool IsEnabled(LogLevel logLevel) => !_isDisposed && logLevel != LogLevel.None && logLevel >= _options.MinimumLevel;

    internal void WriteLog(string categoryName, LogLevel logLevel, string message, Exception? exception)
    {
        if (!IsEnabled(logLevel))
        {
            return;
        }

        string component = ResolveComponent(categoryName);
        string timestamp = DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture);
        string levelString = FormatLogLevel(logLevel);
        string maskedMessage = LogDataMasker.Mask(message);

        var sb = new StringBuilder(128);
        sb.Append(timestamp)
          .Append(" | ")
          .Append(levelString)
          .Append(" | ")
          .Append(component)
          .Append(" | ")
          .Append(maskedMessage);

        if (exception is not null)
        {
            sb.AppendLine();
            sb.Append(LogDataMasker.Mask(exception.ToString()));
        }

        string logLine = sb.ToString();

        lock (_syncRoot)
        {
            if (_isDisposed)
            {
                return;
            }

            try
            {
                EnsureWriter();
                if (_writer is null)
                {
                    return;
                }

                _writer.WriteLine(logLine);
                _currentFileBytes = _writer.BaseStream.Position;

                if (_currentFileBytes >= _options.MaxFileBytes)
                {
                    DoRollover();
                }
            }
            catch (Exception ex)
            {
                _lastFileIoException = ex;
            }
        }
    }

    private void InitializeWriter()
    {
        lock (_syncRoot)
        {
            try
            {
                string logDir;
                try
                {
                    logDir = SafeFileSystem.ResolveStableDirectory(_options.LogDirectory, create: true);
                }
                catch (Exception ex)
                {
                    _lastFileIoException = ex;
                    string fallbackDir = Path.Combine(RuntimePaths.GetTempDir(), "MinecraftServerManager", "Logs");
                    SafeFileSystem.CreateDirectory(fallbackDir);
                    logDir = fallbackDir;
                }

                PruneLogs(logDir, Math.Max(0, _options.MaxArchiveFiles - 1));

                string timestamp = DateTime.Now.ToString("yyyy-MM-dd-HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
                string fileName = $"{timestamp}-p{_options.ProcessId}.log";
                _currentFilePath = Path.Combine(logDir, fileName);

                OpenWriter();
            }
            catch (Exception ex)
            {
                _lastFileIoException = ex;
                _writer = null;
            }
        }
    }

    private void OpenWriter()
    {
        if (string.IsNullOrEmpty(_currentFilePath))
        {
            return;
        }

        _writer?.Dispose();
        var fileStream = new FileStream(_currentFilePath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
        _writer = new StreamWriter(fileStream, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false))
        {
            AutoFlush = true,
        };
        _currentFileBytes = SafeFileSystem.GetFileLength(_currentFilePath);
    }

    private void EnsureWriter()
    {
        if (_writer is null && !string.IsNullOrEmpty(_currentFilePath))
        {
            OpenWriter();
        }
    }

    private void DoRollover()
    {
        try
        {
            _writer?.Flush();
            _writer?.Dispose();
            _writer = null;

            string logDir = Path.GetDirectoryName(_currentFilePath) ?? _options.LogDirectory;
            int maxBackup = Math.Max(0, _options.MaxArchiveFiles - 1);

            if (maxBackup > 0)
            {
                for (int i = maxBackup - 1; i >= 1; i--)
                {
                    string source = $"{_currentFilePath}.{i}";
                    string target = $"{_currentFilePath}.{i + 1}";
                    if (SafeFileSystem.FileExists(source))
                    {
                        SafeFileSystem.MoveWithin(logDir, source, target);
                    }
                }

                string rolloverTarget = $"{_currentFilePath}.1";
                if (SafeFileSystem.FileExists(_currentFilePath))
                {
                    SafeFileSystem.MoveWithin(logDir, _currentFilePath, rolloverTarget);
                }
            }

            PruneLogs(logDir, _options.MaxArchiveFiles);
            OpenWriter();
        }
        catch (Exception ex)
        {
            _lastFileIoException = ex;
            OpenWriter();
        }
    }

    public static void PruneLogs(string logDir, int keep)
    {
        if (!SafeFileSystem.DirectoryExists(logDir))
        {
            return;
        }

        try
        {
            var files = SafeFileSystem.ListBoundedDirectory(logDir)
                .Where(static entry => !entry.IsDirectory &&
                    (entry.FullPath.EndsWith(".log", StringComparison.OrdinalIgnoreCase) || entry.FullPath.Contains(".log.", StringComparison.OrdinalIgnoreCase)))
                .OrderBy(static entry => entry.LastWriteTimeUtc)
                .ToList();

            int removeCount = Math.Max(0, files.Count - Math.Max(0, keep));
            for (int i = 0; i < removeCount; i++)
            {
                SafeFileSystem.DeleteWithin(logDir, files[i].FullPath);
            }
        }
        catch (Exception ex)
        {
            s_lastPruneException = ex;
        }
    }

    private string ResolveComponent(string fallbackCategory)
    {
        string component = string.Empty;

        _scopeProvider?.ForEachScope((scope, _) =>
        {
            if (scope is IReadOnlyDictionary<string, object?> dict &&
                dict.TryGetValue("component", out object? value) &&
                value is not null)
            {
                component = value.ToString() ?? string.Empty;
            }
            else if (scope is IEnumerable<KeyValuePair<string, object?>> pairs)
            {
                foreach (var pair in pairs)
                {
                    if (string.Equals(pair.Key, "component", StringComparison.OrdinalIgnoreCase) && pair.Value is not null)
                    {
                        component = pair.Value.ToString() ?? string.Empty;
                    }
                }
            }
        }, state: (object?)null);

        if (!string.IsNullOrWhiteSpace(component))
        {
            return component;
        }

        return string.IsNullOrWhiteSpace(fallbackCategory) ? "Global" : fallbackCategory;
    }

    private static string FormatLogLevel(LogLevel level) => level switch
    {
        LogLevel.Information => "INFO    ",
        LogLevel.Warning => "WARNING ",
        LogLevel.Error => "ERROR   ",
        LogLevel.Critical => "CRITICAL",
        _ => "INFO    ",
    };

    private sealed class RotatingFileLogger(RotatingFileLoggerProvider provider, string categoryName) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => provider._scopeProvider?.Push(state) ?? NullScope.Instance;

        public bool IsEnabled(LogLevel logLevel) => provider.IsEnabled(logLevel);

        public void Log<TState>(
            LogLevel logLevel,
            EventId eventId,
            TState state,
            Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel))
            {
                return;
            }

            string message = formatter(state, exception);
            provider.WriteLog(categoryName, logLevel, message, exception);
        }
    }

    private sealed class NullScope : IDisposable
    {
        public static NullScope Instance { get; } = new();

        public void Dispose()
        {
        }
    }
}
