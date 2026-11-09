using System.Diagnostics;
using System.Globalization;
using System.Text;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 上次執行未正常結束之偵測結果
/// </summary>
/// <param name="ProcessId">上次執行的行程識別碼</param>
/// <param name="StartedAt">上次執行的啟動時間（原始字串）</param>
/// <param name="LogFilePath">上次執行的記錄檔路徑</param>
/// <param name="LogTail">上次記錄檔最後數行內容</param>
public sealed record UncleanExitReport(string ProcessId, string StartedAt, string? LogFilePath, IReadOnlyList<string> LogTail);

/// <summary>
/// 崩潰診斷：以工作階段標記偵測上次異常結束，並記錄 UI 執行緒拋出的例外，
/// 讓原生層級閃退（例如 WinUI 0xC000027B 快速失敗，不會經過任何受控例外處理常式）仍能從記錄檔追查最後動作。
/// </summary>
public static class CrashDiagnostics
{
    /// <summary>
    /// 工作階段標記檔名（位於記錄檔目錄，正常結束時刪除）
    /// </summary>
    public const string SessionMarkerFileName = "session.marker";

    private const int MaxFirstChanceRecords = 300;
    private const int MaxStackLines = 12;
    private const int LogTailLineCount = 20;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(CrashDiagnostics));
    private static int s_installed;
    private static int s_trackedThreadId;
    private static int s_recordedCount;
    private static string s_logDir = string.Empty;

    [ThreadStatic]
    private static bool t_inHandler;

    /// <summary>
    /// 啟用崩潰診斷；必須於記錄管線初始化後、在 UI 執行緒上呼叫一次
    /// </summary>
    /// <param name="uiThreadId">要追蹤例外的 UI 執行緒受控識別碼</param>
    public static void Install(int uiThreadId)
    {
        if (Interlocked.Exchange(ref s_installed, 1) == 1)
        {
            return;
        }

        s_trackedThreadId = uiThreadId;
        s_logDir = RuntimePaths.GetLogDir();

        try
        {
            if (CheckPreviousSession(s_logDir) is { } report)
            {
                LogUncleanExit(report);
            }

            WriteSessionMarker(s_logDir, Environment.ProcessId, AppLogging.CurrentLogFilePath);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "初始化崩潰診斷工作階段標記失敗: {0}", ex.Message);
        }

        AppDomain.CurrentDomain.FirstChanceException += OnFirstChanceException;
        AppDomain.CurrentDomain.ProcessExit += OnProcessExit;
    }

    /// <summary>
    /// 讀取上次工作階段標記；標記存在代表上次執行未正常結束
    /// </summary>
    public static UncleanExitReport? CheckPreviousSession(string logDir)
    {
        string markerPath = Path.Combine(logDir, SessionMarkerFileName);
        if (!SafeFileSystem.FileExists(markerPath))
        {
            return null;
        }

        string content = SafeFileSystem.ReadAllText(markerPath, Encoding.UTF8, maxBytes: 64 * 1024);
        string[] parts = content.Split('|', 3, StringSplitOptions.TrimEntries);
        string processId = parts.Length > 0 ? parts[0] : "?";
        string startedAt = parts.Length > 1 ? parts[1] : "?";
        string? logFile = parts.Length > 2 && !string.IsNullOrWhiteSpace(parts[2]) ? parts[2] : null;

        IReadOnlyList<string> tail = [];
        if (logFile is not null && SafeFileSystem.FileExists(logFile))
        {
            string logText = SafeFileSystem.ReadAllText(logFile, Encoding.UTF8);
            string[] lines = logText.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            tail = lines.Length > LogTailLineCount ? lines[^LogTailLineCount..] : lines;
        }

        return new UncleanExitReport(processId, startedAt, logFile, tail);
    }

    /// <summary>
    /// 寫入本次工作階段標記
    /// </summary>
    public static void WriteSessionMarker(string logDir, int processId, string? logFilePath)
    {
        string startedAt = DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
        string content = string.Create(CultureInfo.InvariantCulture, $"{processId}|{startedAt}|{logFilePath}");
        if (!AtomicFileWriter.WriteText(Path.Combine(logDir, SessionMarkerFileName), content))
        {
            throw new IOException("無法寫入崩潰診斷工作階段標記");
        }
    }

    /// <summary>
    /// 清除工作階段標記（代表本次執行正常結束）
    /// </summary>
    public static void ClearSessionMarker(string logDir)
    {
        string markerPath = Path.Combine(logDir, SessionMarkerFileName);
        if (SafeFileSystem.FileExists(markerPath))
        {
            SafeFileSystem.DeleteFile(markerPath);
        }
    }

    /// <summary>
    /// 將例外與目前呼叫堆疊整理為單筆診斷文字
    /// </summary>
    public static string FormatFirstChance(Exception exception, string stackTrace)
    {
        ArgumentNullException.ThrowIfNull(exception);
        var sb = new StringBuilder(256);
        sb.Append(exception.GetType().FullName).Append(": ").Append(exception.Message);
        if (exception.HResult != 0)
        {
            sb.Append(CultureInfo.InvariantCulture, $" (HRESULT 0x{exception.HResult:X8})");
        }

        int written = 0;
        foreach (string rawLine in stackTrace.Split('\n'))
        {
            string line = rawLine.Trim();
            if (line.Length == 0 || line.Contains(nameof(CrashDiagnostics), StringComparison.Ordinal))
            {
                continue;
            }

            sb.AppendLine().Append("   ").Append(line);
            if (++written >= MaxStackLines)
            {
                break;
            }
        }

        return sb.ToString();
    }

    private static void LogUncleanExit(UncleanExitReport report)
    {
        var sb = new StringBuilder();
        sb.Append(CultureInfo.InvariantCulture, $"偵測到上次執行未正常結束（PID {report.ProcessId}，啟動於 {report.StartedAt}），可能為原生層級閃退。");
        if (report.LogFilePath is not null)
        {
            sb.AppendLine().Append("上次記錄檔: ").Append(report.LogFilePath);
        }

        if (report.LogTail.Count > 0)
        {
            sb.AppendLine().Append("上次記錄檔最後內容:");
            foreach (string line in report.LogTail)
            {
                sb.AppendLine().Append("   > ").Append(line);
            }
        }

        Logger.Warning("{0}", sb.ToString());
    }

    private static void OnFirstChanceException(object? sender, System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs e)
    {
        if (t_inHandler ||
            Environment.CurrentManagedThreadId != s_trackedThreadId ||
            e.Exception is OperationCanceledException)
        {
            return;
        }

        t_inHandler = true;
        try
        {
            int count = Interlocked.Increment(ref s_recordedCount);
            if (count > MaxFirstChanceRecords)
            {
                return;
            }

            string detail = FormatFirstChance(e.Exception, new StackTrace(1, false).ToString());
            Logger.Warning("UI 執行緒拋出例外（若隨後閃退，此即最後線索）: {0}", detail);
            if (count == MaxFirstChanceRecords)
            {
                Logger.Warning("UI 執行緒例外追蹤已達本次上限 {0} 筆，後續不再記錄", MaxFirstChanceRecords);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("記錄 UI 執行緒例外追蹤失敗: {0}", ex.Message);
        }
        finally
        {
            t_inHandler = false;
        }
    }

    private static void OnProcessExit(object? sender, EventArgs e)
    {
        try
        {
            Logger.Information("應用程式行程正常結束 (結束代碼: {0})", Environment.ExitCode);
            ClearSessionMarker(s_logDir);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "清除崩潰診斷工作階段標記失敗: {0}", ex.Message);
        }
    }
}
