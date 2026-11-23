using System.Collections.Concurrent;
using System.Globalization;
using System.Text;
using Microsoft.Extensions.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>依設定的單檔上限輪替、保留有限份數的檔案記錄器提供者</summary>
/// <remarks>
/// 檔案操作直接使用 BCL（A1 白名單），不經 <c>SafeFileSystem</c>，避免記錄器在輪替中再度記錄而遞迴。
/// Warning 以上立即排清，其餘每秒批次排清。
/// </remarks>
public sealed class RotatingFileLoggerProvider : ILoggerProvider
{
    private static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);
    private static readonly TimeSpan FlushInterval = TimeSpan.FromSeconds(1);
    private static readonly int NewLineByteCount = Utf8NoBom.GetByteCount(Environment.NewLine);
    private static readonly EnumerationOptions LogEnumeration = new()
    {
        AttributesToSkip = FileAttributes.ReparsePoint,
        IgnoreInaccessible = true,
    };

    private readonly string _logDirectory;
    private readonly long _maxFileBytes;
    private readonly int _maxArchiveFiles;
    private readonly LogLevel _minimumLevel;
    private readonly int _processId;
    private readonly Lock _syncRoot = new();
    private readonly ConcurrentDictionary<string, RotatingFileLogger> _loggers = new(StringComparer.OrdinalIgnoreCase);
    private readonly Timer _flushTimer;
    private StreamWriter? _writer;
    private string _currentFilePath = string.Empty;
    private long _currentFileBytes;
    private long _nextRolloverThresholdBytes;
    private const long RolloverRetryBackoffBytes = 512L * 1024;
    private bool _pendingFlush;
    private bool _isWriting;
    private volatile bool _isDisposed;

    public RotatingFileLoggerProvider(RotatingFileLoggerOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentException.ThrowIfNullOrWhiteSpace(options.LogDirectory);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(options.MaxFileBytes);
        ArgumentOutOfRangeException.ThrowIfLessThan(options.MaxArchiveFiles, 1);

        _logDirectory = options.LogDirectory;
        _maxFileBytes = options.MaxFileBytes;
        _nextRolloverThresholdBytes = options.MaxFileBytes;
        _maxArchiveFiles = options.MaxArchiveFiles;
        _minimumLevel = options.MinimumLevel;
        _processId = options.ProcessId;

        InitializeWriter();
        _flushTimer = new Timer(static state => ((RotatingFileLoggerProvider)state!).FlushPending(), this, FlushInterval, FlushInterval);
    }

    /// <summary>目前寫入中的記錄檔完整路徑；初始化失敗時為空字串</summary>
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
            CloseWriter();
        }

        _flushTimer.Dispose();
    }

    internal bool IsEnabled(LogLevel logLevel) => !_isDisposed && logLevel != LogLevel.None && logLevel >= _minimumLevel;

    internal void WriteLog(string categoryName, LogLevel logLevel, string message, Exception? exception)
    {
        if (!IsEnabled(logLevel))
        {
            return;
        }

        string component = string.IsNullOrWhiteSpace(categoryName) ? "Global" : categoryName;
        string timestamp = DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);

        var sb = new StringBuilder(128);
        sb.Append(timestamp)
          .Append(" | ")
          .Append(FormatLogLevel(logLevel))
          .Append(" | ")
          .Append(component)
          .Append(" | ")
          .Append(LogDataMasker.Mask(message));

        if (exception is not null)
        {
            sb.AppendLine();
            sb.Append(LogDataMasker.Mask(exception.ToString()));
        }

        string logLine = sb.ToString();

        lock (_syncRoot)
        {
            // 重入防護：輪替或寫入過程中的同執行緒記錄直接捨棄，避免遞迴
            if (_isDisposed || _isWriting)
            {
                return;
            }

            _isWriting = true;
            try
            {
                EnsureWriter();
                if (_writer is null)
                {
                    return;
                }

                _writer.WriteLine(logLine);
                _currentFileBytes += Utf8NoBom.GetByteCount(logLine) + NewLineByteCount;

                if (logLevel >= LogLevel.Warning)
                {
                    _writer.Flush();
                    _pendingFlush = false;
                }
                else
                {
                    _pendingFlush = true;
                }

                if (_currentFileBytes >= _nextRolloverThresholdBytes)
                {
                    DoRollover();
                }
            }
            catch (Exception)
            {
                // 日誌器無法記錄自身的寫入失敗
            }
            finally
            {
                _isWriting = false;
            }
        }
    }

    /// <summary>刪除最舊的記錄檔，只保留最新 <paramref name="keep"/> 份</summary>
    internal static void PruneLogs(string logDir, int keep)
    {
        try
        {
            var directory = new DirectoryInfo(logDir);
            if (!directory.Exists)
            {
                return;
            }

            var files = directory.EnumerateFiles("*", LogEnumeration)
                .Where(static file => IsLogFileName(file.Name))
                .OrderBy(static file => file.LastWriteTimeUtc)
                .ToList();

            int removeCount = files.Count - Math.Max(0, keep);
            for (int i = 0; i < removeCount; i++)
            {
                TryDelete(files[i].FullName);
            }
        }
        catch (Exception)
        {
            // 日誌器無法記錄自身的清理失敗；保留舊檔不影響後續寫入
        }
    }

    private void InitializeWriter()
    {
        lock (_syncRoot)
        {
            try
            {
                string logDir = ResolveLogDirectory();
                PruneLogs(logDir, _maxArchiveFiles - 1);

                string timestamp = DateTime.Now.ToString("yyyy-MM-dd-HH-mm-ss", CultureInfo.InvariantCulture);
                _currentFilePath = Path.Combine(logDir, $"{timestamp}-p{_processId}.log");
                OpenWriter(truncate: false);
            }
            catch (Exception)
            {
                // 日誌器無法記錄自身的初始化失敗；放棄寫入器，後續記錄將被忽略
                _writer = null;
            }
        }
    }

    private string ResolveLogDirectory()
    {
        try
        {
            return EnsureDirectory(_logDirectory);
        }
        catch (Exception)
        {
            return EnsureDirectory(Path.Combine(RuntimePaths.GetTempDir(), "MinecraftServerManager", "Logs"));
        }
    }

    private static string EnsureDirectory(string path)
    {
        var directory = Directory.CreateDirectory(Path.GetFullPath(path));
        if (directory.Attributes.HasFlag(FileAttributes.ReparsePoint))
        {
            throw new IOException($"記錄目錄不可為重新分析點：{directory.FullName}");
        }

        return directory.FullName;
    }

    private void OpenWriter(bool truncate)
    {
        if (string.IsNullOrEmpty(_currentFilePath))
        {
            return;
        }

        CloseWriter();
        FileStream? fileStream = null;
        try
        {
            fileStream = new FileStream(_currentFilePath, truncate ? FileMode.Create : FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
            _currentFileBytes = fileStream.Length;
            _writer = new StreamWriter(fileStream, Utf8NoBom);
            fileStream = null;
        }
        finally
        {
            fileStream?.Dispose();
        }
    }

    private void CloseWriter()
    {
        try
        {
            _writer?.Flush();
            _writer?.Dispose();
        }
        catch (Exception)
        {
            // 日誌器無法記錄自身的關閉失敗
        }
        finally
        {
            _writer = null;
            _pendingFlush = false;
        }
    }

    private void EnsureWriter()
    {
        if (_writer is null && !string.IsNullOrEmpty(_currentFilePath))
        {
            OpenWriter(truncate: false);
        }
    }

    private void FlushPending()
    {
        lock (_syncRoot)
        {
            if (_isDisposed || !_pendingFlush || _writer is null)
            {
                return;
            }

            try
            {
                _writer.Flush();
            }
            catch (Exception)
            {
                // 日誌器無法記錄自身的排清失敗
            }

            _pendingFlush = false;
        }
    }

    private void DoRollover()
    {
        int maxBackup = _maxArchiveFiles - 1;
        try
        {
            CloseWriter();
            if (maxBackup == 0)
            {
                // 只保留 1 份：截斷目前檔案重新寫入
                OpenWriter(truncate: true);
                _nextRolloverThresholdBytes = _maxFileBytes;
                return;
            }

            for (int i = maxBackup - 1; i >= 1; i--)
            {
                TryMove($"{_currentFilePath}.{i}", $"{_currentFilePath}.{i + 1}");
            }

            TryMove(_currentFilePath, $"{_currentFilePath}.1");
            PruneLogs(Path.GetDirectoryName(_currentFilePath)!, maxBackup);
            OpenWriter(truncate: false);
            _nextRolloverThresholdBytes = _maxFileBytes;
        }
        catch (Exception)
        {
            // 輪替失敗時仍嘗試重新開啟寫入器，確保後續記錄不中斷；推進門檻避免每筆重試風暴
            try
            {
                OpenWriter(truncate: false);
            }
            catch (Exception)
            {
                _writer = null;
            }

            _nextRolloverThresholdBytes = _currentFileBytes + RolloverRetryBackoffBytes;
        }
    }

    private static void TryMove(string source, string target)
    {
        try
        {
            if (File.Exists(source))
            {
                File.Move(source, target, overwrite: true);
            }
        }
        catch (Exception)
        {
            // 單一檔案搬移失敗不影響其餘輪替
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception)
        {
            // 單一檔案刪除失敗不影響其餘清理
        }
    }

    private static bool IsLogFileName(string fileName) =>
        fileName.EndsWith(".log", StringComparison.OrdinalIgnoreCase) || fileName.Contains(".log.", StringComparison.OrdinalIgnoreCase);

    private static string FormatLogLevel(LogLevel level) => level switch
    {
        LogLevel.Trace => "TRACE   ",
        LogLevel.Debug => "DEBUG   ",
        LogLevel.Information => "INFO    ",
        LogLevel.Warning => "WARNING ",
        LogLevel.Error => "ERROR   ",
        LogLevel.Critical => "CRITICAL",
        _ => "INFO    ",
    };

    private sealed class RotatingFileLogger(RotatingFileLoggerProvider provider, string categoryName) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

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

            provider.WriteLog(categoryName, logLevel, formatter(state, exception), exception);
        }
    }
}
