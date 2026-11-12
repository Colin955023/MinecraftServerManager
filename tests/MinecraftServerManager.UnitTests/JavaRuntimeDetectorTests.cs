using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>Java 執行環境偵測快取與單檔解壓殘留清理單元測試</summary>
[Collection("EnvironmentVariableCollection")]
public sealed class JavaRuntimeDetectorTests
{
    [Fact]
    public async Task DetectAsync_UsesCacheWhenFileTimestampAndSizeMatch()
    {
        using var tempDir = new TempDirectory("msm-java-detector-");
        string javaBinDir = Path.Combine(tempDir.FullName, "jdk-21", "bin");
        Directory.CreateDirectory(javaBinDir);
        string javaExe = Path.Combine(javaBinDir, "java.exe");
        File.WriteAllText(javaExe, "fake java binary");

        string? origJavaHome = Environment.GetEnvironmentVariable("JAVA_HOME");
        string? origPath = Environment.GetEnvironmentVariable("PATH");
        string? origDataDir = Environment.GetEnvironmentVariable("MSM_USER_DATA_DIR");

        int processStartCount = 0;
        var runner = new StubProcessRunner(_ =>
        {
            Interlocked.Increment(ref processStartCount);
            return new StubManagedProcess(
                exitCode: 0,
                interactive: false,
                initialOutputs:
                [
                    new ProcessOutput(ProcessOutputKind.StandardError, "openjdk version \"21.0.4\" 2024-07-16 LTS"),
                    new ProcessOutput(ProcessOutputKind.StandardError, "OpenJDK Runtime Environment Temurin-21.0.4+7 (build 21.0.4+7-LTS)"),
                    new ProcessOutput(ProcessOutputKind.StandardError, "OpenJDK 64-Bit Server VM Temurin-21.0.4+7 (build 21.0.4+7-LTS, mixed mode, sharing)")
                ]);
        });

        try
        {
            Environment.SetEnvironmentVariable("JAVA_HOME", Path.Combine(tempDir.FullName, "jdk-21"));
            Environment.SetEnvironmentVariable("PATH", javaBinDir);
            Environment.SetEnvironmentVariable("MSM_USER_DATA_DIR", tempDir.FullName);

            var detector = new JavaRuntimeDetector(runner);

            // 第一次強制偵測應呼叫外部行程並寫入快取
            var first = await detector.DetectAsync(forceRefresh: true);
            Assert.Contains(first, j => string.Equals(j.ExecutablePath, javaExe, StringComparison.OrdinalIgnoreCase) && j.MajorVersion == 21);
            int callsAfterFirst = processStartCount;
            Assert.True(callsAfterFirst >= 1);

            // 新執行個體讀取磁碟快取：若該 java.exe 時間戳記與檔案大小未變，不應對此 javaExe 重新啟動行程
            int targetExeCalls = 0;
            var secondRunner = new StubProcessRunner(spec =>
            {
                if (string.Equals(spec.FileName, javaExe, StringComparison.OrdinalIgnoreCase))
                {
                    Interlocked.Increment(ref targetExeCalls);
                }

                return new StubManagedProcess(1);
            });
            var cachedDetector = new JavaRuntimeDetector(secondRunner);
            var second = await cachedDetector.DetectAsync(forceRefresh: false);

            Assert.Contains(second, j => string.Equals(j.ExecutablePath, javaExe, StringComparison.OrdinalIgnoreCase) && j.MajorVersion == 21);
            Assert.Equal(0, targetExeCalls);
        }
        finally
        {
            Environment.SetEnvironmentVariable("JAVA_HOME", origJavaHome);
            Environment.SetEnvironmentVariable("PATH", origPath);
            Environment.SetEnvironmentVariable("MSM_USER_DATA_DIR", origDataDir);
        }
    }

    [Fact]
    public void CleanupStaleSingleFileExtractDirectories_DoesNotThrow()
    {
        var exception = Record.Exception(() => _ = RuntimePaths.CleanupStaleSingleFileExtractDirectories());
        Assert.Null(exception);
    }
}
