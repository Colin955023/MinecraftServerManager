using Microsoft.Extensions.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 輪替檔案日誌設定選項
/// </summary>
public sealed class RotatingFileLoggerOptions
{
    public const long DefaultMaxFileBytes = 10 * 1024 * 1024; // 10 MiB
    public const int DefaultMaxArchiveFiles = 10;

    public string LogDirectory { get; set; } = RuntimePaths.GetLogDir();

    public long MaxFileBytes { get; set; } = DefaultMaxFileBytes;

    public int MaxArchiveFiles { get; set; } = DefaultMaxArchiveFiles;

    public LogLevel MinimumLevel { get; set; } = RuntimePaths.IsDevelopmentEnvironment()
        ? LogLevel.Debug
        : LogLevel.Information;

    public int ProcessId { get; set; } = Environment.ProcessId;

    public bool OutputToConsole { get; set; } = RuntimePaths.IsDevelopmentEnvironment();
}
