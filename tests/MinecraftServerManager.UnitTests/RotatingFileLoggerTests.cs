using System.Diagnostics.CodeAnalysis;
using Microsoft.Extensions.Logging;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

[SuppressMessage("Performance", "CA1848", Justification = "單元測試需驗證 ILogger 擴充方法行為")]
[SuppressMessage("Performance", "CA1873", Justification = "單元測試需驗證 ILogger 擴充方法行為")]
[SuppressMessage("Usage", "CA2254", Justification = "單元測試動態提供訊息範本")]
public sealed class RotatingFileLoggerTests
{
    [Fact]
    public void MaskerHidesPasswordsAndTokens()
    {
        string input = "連線字串包含 password=mySecretPassword123 與 token=xyz890 以及 Bearer eyJhbGciOiJIUzI1Ni";
        string masked = LogDataMasker.Mask(input);

        Assert.DoesNotContain("mySecretPassword123", masked, StringComparison.Ordinal);
        Assert.DoesNotContain("xyz890", masked, StringComparison.Ordinal);
        Assert.DoesNotContain("eyJhbGciOiJIUzI1Ni", masked, StringComparison.Ordinal);
        Assert.Contains("password=***", masked, StringComparison.Ordinal);
        Assert.Contains("token=***", masked, StringComparison.Ordinal);
        Assert.Contains("Bearer ***", masked, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void LoggerOutputsFormattedMessageWithComponentAndLevel()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
            var options = new RotatingFileLoggerOptions
            {
                LogDirectory = tempDir,
                MinimumLevel = LogLevel.Debug,
                ProcessId = 1234,
                OutputToConsole = false,
            };

            using var provider = new RotatingFileLoggerProvider(options);
            var scopeProvider = new LoggerExternalScopeProvider();
            provider.SetScopeProvider(scopeProvider);

            var logger = provider.CreateLogger("TestModule");
            using (logger.BeginScope(new Dictionary<string, object?> { ["component"] = "ServerCore" }))
            {
                logger.LogInformation("伺服器準備啟動");
                logger.LogWarning("記憶體設定過低");
            }

            provider.Dispose();

            string[] logFiles = Directory.GetFiles(tempDir, "*.log");
            Assert.Single(logFiles);

            string content = File.ReadAllText(logFiles[0]);
            Assert.Contains(" | INFO     | ServerCore | 伺服器準備啟動", content, StringComparison.Ordinal);
            Assert.Contains(" | WARNING  | ServerCore | 記憶體設定過低", content, StringComparison.Ordinal);
        }
        finally
        {
            Directory.Delete(tempDir, recursive: true);
        }
    }

    [Fact]
    public void LoggerIncludesExceptionStackTrace()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
            var options = new RotatingFileLoggerOptions
            {
                LogDirectory = tempDir,
                MinimumLevel = LogLevel.Debug,
                ProcessId = 5678,
                OutputToConsole = false,
            };

            using var provider = new RotatingFileLoggerProvider(options);
            var logger = provider.CreateLogger("ExceptionLogger");

            try
            {
                throw new InvalidOperationException("測試例外錯誤");
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "發生嚴重異常");
            }

            provider.Dispose();

            string[] logFiles = Directory.GetFiles(tempDir, "*.log");
            Assert.Single(logFiles);

            string content = File.ReadAllText(logFiles[0]);
            Assert.Contains(" | ERROR    | ExceptionLogger | 發生嚴重異常", content, StringComparison.Ordinal);
            Assert.Contains("System.InvalidOperationException: 測試例外錯誤", content, StringComparison.Ordinal);
        }
        finally
        {
            Directory.Delete(tempDir, recursive: true);
        }
    }

    [Fact]
    public void LoggerRotatesWhenExceedingMaxFileBytes()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
            var options = new RotatingFileLoggerOptions
            {
                LogDirectory = tempDir,
                MaxFileBytes = 300, // 極小限制以觸發輪替
                MaxArchiveFiles = 5,
                MinimumLevel = LogLevel.Debug,
                ProcessId = 9999,
                OutputToConsole = false,
            };

            using var provider = new RotatingFileLoggerProvider(options);
            var logger = provider.CreateLogger("RotationTest");

            // 寫入足量訊息使總長度遠超 300 bytes
            for (int i = 0; i < 20; i++)
            {
                logger.LogInformation("這是一條測試日誌訊息編號 {Index} 用於觸發檔案自動輪替機制", i);
            }

            provider.Dispose();

            string[] allFiles = Directory.GetFiles(tempDir);
            // 應存在基底檔案與至少一個 .1 備份檔案
            Assert.True(allFiles.Length >= 2);
            Assert.Contains(allFiles, f => f.EndsWith(".1", StringComparison.OrdinalIgnoreCase));
        }
        finally
        {
            Directory.Delete(tempDir, recursive: true);
        }
    }

    [Fact]
    public void PruneLogsDeletesOldestFilesWhenExceedingKeepCount()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
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
            Assert.DoesNotContain(remaining, f => f.Contains("-01-", StringComparison.Ordinal));
            Assert.DoesNotContain(remaining, f => f.Contains("-02-", StringComparison.Ordinal));
            Assert.Contains(remaining, f => f.Contains("-05-", StringComparison.Ordinal));
        }
        finally
        {
            Directory.Delete(tempDir, recursive: true);
        }
    }

    [Fact]
    public async Task ConcurrentWritesDoNotThrowOrCorrupt()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
            var options = new RotatingFileLoggerOptions
            {
                LogDirectory = tempDir,
                MinimumLevel = LogLevel.Information,
                ProcessId = 1111,
                OutputToConsole = false,
            };

            using var provider = new RotatingFileLoggerProvider(options);
            var logger = provider.CreateLogger("ConcurrencyTest");

            var tasks = Enumerable.Range(0, 50).Select(i => Task.Run(() =>
            {
                logger.LogInformation("執行緒 {ThreadId} 寫入平行測試日誌項 {Index}", Environment.CurrentManagedThreadId, i);
            }));

            await Task.WhenAll(tasks).WaitAsync(TimeSpan.FromSeconds(15));

            provider.Dispose();

            string[] files = Directory.GetFiles(tempDir, "*.log");
            Assert.Single(files);

            string[] lines = File.ReadAllLines(files[0]);
            Assert.Equal(50, lines.Length);
        }
        finally
        {
            try
            {
                if (Directory.Exists(tempDir))
                {
                    Directory.Delete(tempDir, recursive: true);
                }
            }
            catch
            {
            }
        }
    }

    [Fact]
    public void SafeFileSystemMoveWithinAndDeleteWithinEnforceBoundaries()
    {
        string tempDir = CreateTemporaryDirectory();
        string externalDir = CreateTemporaryDirectory();
        try
        {
            string subFile = Path.Combine(tempDir, "inner.txt");
            File.WriteAllText(subFile, "test");

            string targetFile = Path.Combine(tempDir, "moved.txt");
            bool moveSuccess = SafeFileSystem.MoveWithin(tempDir, subFile, targetFile);
            Assert.True(moveSuccess);
            Assert.False(File.Exists(subFile));
            Assert.True(File.Exists(targetFile));

            // 嘗試移動到外部目錄應被拒絕
            string extTarget = Path.Combine(externalDir, "escaped.txt");
            bool invalidMove = SafeFileSystem.MoveWithin(tempDir, targetFile, extTarget);
            Assert.False(invalidMove);
            Assert.True(File.Exists(targetFile));

            // 嘗試刪除外部目錄檔案應被拒絕
            string extFile = Path.Combine(externalDir, "safe.txt");
            File.WriteAllText(extFile, "external");
            bool invalidDelete = SafeFileSystem.DeleteWithin(tempDir, extFile);
            Assert.False(invalidDelete);
            Assert.True(File.Exists(extFile));

            // 正常刪除內部檔案應成功
            bool deleteSuccess = SafeFileSystem.DeleteWithin(tempDir, targetFile);
            Assert.True(deleteSuccess);
            Assert.False(File.Exists(targetFile));
        }
        finally
        {
            Directory.Delete(tempDir, recursive: true);
            Directory.Delete(externalDir, recursive: true);
        }
    }

    [Fact]
    public void RuntimePathsRespectsEnvironmentOverride()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
            Environment.SetEnvironmentVariable("MSM_USER_DATA_DIR", tempDir);
            try
            {
                Assert.Equal(Path.GetFullPath(tempDir), RuntimePaths.GetUserDataDir());
                Assert.Equal(Path.Combine(Path.GetFullPath(tempDir), "Logs"), RuntimePaths.GetLogDir());
                Assert.Equal(Path.Combine(Path.GetFullPath(tempDir), "Cache"), RuntimePaths.GetCacheDir());
            }
            finally
            {
                Environment.SetEnvironmentVariable("MSM_USER_DATA_DIR", null);
            }
        }
        finally
        {
            Directory.Delete(tempDir, recursive: true);
        }
    }

    [Fact]
    public void AppLoggingCreatesAndInitializesLogger()
    {
        string tempDir = CreateTemporaryDirectory();
        try
        {
            var options = new RotatingFileLoggerOptions
            {
                LogDirectory = tempDir,
                MinimumLevel = LogLevel.Debug,
                ProcessId = 7777,
                OutputToConsole = false,
            };

            AppLogging.Shutdown();
            AppLogging.Initialize(options);

            var logger = AppLogging.CreateComponentLogger("AppTest");
            logger.Information("AppLogging 初始化完成");

            AppLogging.Shutdown();

            string[] logFiles = Directory.GetFiles(tempDir, "*.log");
            Assert.Single(logFiles);

            string content = File.ReadAllText(logFiles[0]);
            Assert.Contains(" | INFO     | AppTest | AppLogging 初始化完成", content, StringComparison.Ordinal);
        }
        finally
        {
            AppLogging.Shutdown();
            Directory.Delete(tempDir, recursive: true);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-log-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
