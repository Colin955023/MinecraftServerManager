using System.Diagnostics.CodeAnalysis;
using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.Infrastructure.Logging;

public sealed class ComponentLogger
{
    private readonly ILogger _logger;
    private readonly IReadOnlyDictionary<string, object?> _context;

    public ComponentLogger(ILogger logger)
        : this(logger, new Dictionary<string, object?>())
    {
    }

    private ComponentLogger(ILogger logger, IReadOnlyDictionary<string, object?> context)
    {
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _context = context;
    }

    public ComponentLogger Bind(string key, object? value)
    {
        ArgumentException.ThrowIfNullOrEmpty(key);
        var context = new Dictionary<string, object?>(_context, StringComparer.Ordinal)
        {
            [key] = value,
        };
        return new ComponentLogger(_logger, context);
    }

    public void Debug(string message, params object?[] args) => Log(LogLevel.Debug, null, message, args);

    public void Information(string message, params object?[] args) => Log(LogLevel.Information, null, message, args);

    public void Warning(string message, params object?[] args) => Log(LogLevel.Warning, null, message, args);

    public void Error(string message, params object?[] args) => Log(LogLevel.Error, null, message, args);

    public void Error(Exception? exception, string message, params object?[] args) => Log(LogLevel.Error, exception, message, args);

    [SuppressMessage("Performance", "CA1848", Justification = "元件化記錄器需保留呼叫端的動態記錄層級與訊息範本")]
    [SuppressMessage("Usage", "CA2254", Justification = "元件化記錄器的訊息範本由各工作流程提供")]
    private void Log(LogLevel level, Exception? exception, string message, object?[] args)
    {
        if (_context.Count == 0)
        {
            _logger.Log(level, exception, message, args);
            return;
        }

        using var scope = _logger.BeginScope(_context);
        _logger.Log(level, exception, message, args);
    }
}
