using System.Diagnostics.CodeAnalysis;
using Microsoft.Extensions.Logging;

namespace MinecraftServerManager.UnitTests.Logging;

[SuppressMessage("Performance", "CA1848", Justification = "單元測試需驗證 ILogger 擴充方法行為")]
[SuppressMessage("Performance", "CA1873", Justification = "單元測試需驗證 ILogger 擴充方法行為")]
[SuppressMessage("Usage", "CA2254", Justification = "單元測試動態提供訊息範本")]
public sealed class RotatingFileLoggerTests
{
    [Fact]
    public void Log_InformationMessage_WritesComponentAndLevel()
    {
        using var tempDirTemp = new TempDirectory("msm-log-test-");
        string tempDir = tempDirTemp.FullName;
        var options = new RotatingFileLoggerOptions
        {
            LogDirectory = tempDir,
            MinimumLevel = LogLevel.Information,
            ProcessId = 1234,
        };

        using var provider = new RotatingFileLoggerProvider(options);

        var logger = provider.CreateLogger("ServerCore");
        logger.LogInformation("伺服器準備啟動");
        logger.LogWarning("記憶體設定過低");

        provider.Dispose();

        string[] logFiles = Directory.GetFiles(tempDir, "*.log");
        string item = Assert.Single(logFiles);

        string content = File.ReadAllText(item);
        Assert.Contains(" | INFO     | ServerCore | 伺服器準備啟動", content, StringComparison.Ordinal);
        Assert.Contains(" | WARNING  | ServerCore | 記憶體設定過低", content, StringComparison.Ordinal);
    }

    [Fact]
    public void Log_WithException_WritesStackTrace()
    {
        using var tempDirTemp = new TempDirectory("msm-log-test-");
        string tempDir = tempDirTemp.FullName;
        var options = new RotatingFileLoggerOptions
        {
            LogDirectory = tempDir,
            MinimumLevel = LogLevel.Information,
            ProcessId = 5678,
        };

        using var provider = new RotatingFileLoggerProvider(options);
        var logger = provider.CreateLogger("ExceptionLogger");

        try
        {
            throw new InvalidOperationException("測試例外錯誤");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "發生嚴重例外");
        }

        provider.Dispose();

        string[] logFiles = Directory.GetFiles(tempDir, "*.log");
        string item = Assert.Single(logFiles);

        string content = File.ReadAllText(item);
        Assert.Contains(" | ERROR    | ExceptionLogger | 發生嚴重例外", content, StringComparison.Ordinal);
        Assert.Contains("System.InvalidOperationException: 測試例外錯誤", content, StringComparison.Ordinal);
    }

    [Fact]
    public void Log_ExceedsMaxFileBytes_RotatesFile()
    {
        using var tempDirTemp = new TempDirectory("msm-log-test-");
        string tempDir = tempDirTemp.FullName;
        var options = new RotatingFileLoggerOptions
        {
            LogDirectory = tempDir,
            MaxFileBytes = 300, // 極小限制以觸發輪替
            MaxArchiveFiles = 5,
            MinimumLevel = LogLevel.Information,
            ProcessId = 9999,
        };

        using var provider = new RotatingFileLoggerProvider(options);
        var logger = provider.CreateLogger("RotationTest");

        // 寫入足量訊息使總長度遠超 300 bytes
        for (int i = 0; i < 20; i++)
        {
            logger.LogInformation("這是一條測試記錄訊息編號 {Index} 用於觸發檔案自動輪替機制", i);
        }

        provider.Dispose();

        string[] allFiles = Directory.GetFiles(tempDir);
        // 應存在基底檔案與至少一個 .1 備份檔案
        Assert.True(allFiles.Length >= 2);
        Assert.Contains(allFiles, static f => f.EndsWith(".1", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void PruneLogs_ExceedsKeepCount_DeletesOldest()
    {
        using var tempDirTemp = new TempDirectory("msm-log-test-");
        string tempDir = tempDirTemp.FullName;
        var now = DateTime.UtcNow;
        for (int i = 1; i <= 5; i++)
        {
            string filePath = Path.Combine(tempDir, $"2026-09-16-0{i}-00-00-p100.log");
            File.WriteAllText(filePath, $"log content {i}");
            File.SetLastWriteTimeUtc(filePath, now.AddMinutes(i));
        }

        Assert.Equal(5, Directory.GetFiles(tempDir).Length);

        // 保留最新的 3 個檔案
        RotatingFileLoggerProvider.PruneLogs(tempDir, 3);

        string[] remaining = Directory.GetFiles(tempDir);
        Assert.Equal(3, remaining.Length);

        // 舊的 01 與 02 應被清理，保留 03, 04, 05
        Assert.DoesNotContain(remaining, static f => f.Contains("-01-", StringComparison.Ordinal));
        Assert.DoesNotContain(remaining, static f => f.Contains("-02-", StringComparison.Ordinal));
        Assert.Contains(remaining, static f => f.Contains("-05-", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Log_ConcurrentWrites_KeepsLinesIntact()
    {
        using var tempDirTemp = new TempDirectory("msm-log-test-");
        string tempDir = tempDirTemp.FullName;
        var options = new RotatingFileLoggerOptions
        {
            LogDirectory = tempDir,
            MinimumLevel = LogLevel.Information,
            ProcessId = 1111,
        };

        using var provider = new RotatingFileLoggerProvider(options);
        var logger = provider.CreateLogger("ConcurrencyTest");

        var tasks = Enumerable.Range(0, 50).Select(i => Task.Run(() =>
        {
            logger.LogInformation("執行緒 {ThreadId} 寫入平行測試記錄項 {Index}", Environment.CurrentManagedThreadId, i);
        }));

        await Task.WhenAll(tasks).WaitAsync(TimeSpan.FromSeconds(15), TestContext.Current.CancellationToken);

        provider.Dispose();

        string[] files = Directory.GetFiles(tempDir, "*.log");
        string item = Assert.Single(files);

        string[] lines = File.ReadAllLines(item);
        Assert.Equal(50, lines.Length);
    }
}
