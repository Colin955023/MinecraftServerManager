using System.Diagnostics.CodeAnalysis;
using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 以元件名稱為類別的記錄器包裝，僅開放 Information／Warning／Error 三種等級
/// </summary>
public sealed class ComponentLogger(ILogger logger)
{
    private readonly ILogger _logger = logger ?? throw new ArgumentNullException(nameof(logger));

    public void Information(string message, params object?[] args) => Log(LogLevel.Information, null, message, args);

    public void Warning(string message, params object?[] args) => Log(LogLevel.Warning, null, message, args);

    public void Warning(Exception? exception, string message, params object?[] args) => Log(LogLevel.Warning, exception, message, args);

    public void Error(string message, params object?[] args) => Log(LogLevel.Error, null, message, args);

    public void Error(Exception? exception, string message, params object?[] args) => Log(LogLevel.Error, exception, message, args);

    [SuppressMessage("Performance", "CA1848", Justification = "元件化記錄器需保留呼叫端的動態記錄層級與訊息範本")]
    [SuppressMessage("Usage", "CA2254", Justification = "元件化記錄器的訊息範本由各工作流程提供")]
    private void Log(LogLevel level, Exception? exception, string message, object?[] args) =>
        _logger.Log(level, exception, message, args);
}
