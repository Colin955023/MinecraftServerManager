using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Process;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ProcessRunnerTests
{
    [Fact]
    public async Task StartsWithoutShellAndCapturesStandardOutput()
    {
        var runner = new ProcessRunner();
        var output = new List<ProcessOutput>();
        await using var process = await runner.StartAsync(new ProcessStartSpec(
            "dotnet",
            ["--version"]));
        process.OutputReceived += output.Add;

        var result = await process.WaitForExitAsync();

        Assert.True(process.Pid > 0);
        Assert.Equal(0, result.ExitCode);
        Assert.False(result.WasForceStopped);
        Assert.Contains(output, static item => item.Kind == ProcessOutputKind.StandardOutput);
    }

    [Fact]
    public async Task RejectsMissingAbsoluteExecutable()
    {
        var runner = new ProcessRunner();

        await Assert.ThrowsAsync<FileNotFoundException>(() => runner.StartAsync(new ProcessStartSpec(
            Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"), "missing.exe"),
            [])));
    }

    [Fact]
    public async Task RejectsEmptyExecutableName()
    {
        var runner = new ProcessRunner();

        await Assert.ThrowsAsync<ArgumentException>(() => runner.StartAsync(new ProcessStartSpec(
            "   ",
            [])));
    }

    [Fact]
    public async Task RejectsMissingWorkingDirectory()
    {
        var runner = new ProcessRunner();

        await Assert.ThrowsAsync<DirectoryNotFoundException>(() => runner.StartAsync(new ProcessStartSpec(
            "dotnet",
            ["--version"],
            WorkingDirectory: Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N")))));
    }

    [Fact]
    public async Task StartsBatchScriptWithSpacesAndCapturesOutput()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "msm test batch " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        try
        {
            string batPath = Path.Combine(tempDir, "script with space.bat");
            File.WriteAllText(batPath, "@echo off\r\necho BATCH_OUTPUT_%1\r\n");

            var runner = new ProcessRunner();
            var output = new List<ProcessOutput>();

            await using var process = await runner.StartAsync(new ProcessStartSpec(
                batPath,
                ["TEST_ARG"],
                WorkingDirectory: tempDir));
            process.OutputReceived += output.Add;

            var result = await process.WaitForExitAsync();

            Assert.True(process.Pid > 0);
            Assert.Equal(0, result.ExitCode);
            Assert.False(result.WasForceStopped);
            Assert.Contains(output, static item => item.Text.Contains("BATCH_OUTPUT_TEST_ARG", StringComparison.Ordinal));
        }
        finally
        {
            if (Directory.Exists(tempDir))
            {
                Directory.Delete(tempDir, recursive: true);
            }
        }
    }

    [Fact]
    public void OpenFile_RejectsDangerousExtensionsBeforeShellExecution()
    {
        string tempFile = Path.Combine(Path.GetTempPath(), $"reject-{Guid.NewGuid():N}.exe");
        File.WriteAllText(tempFile, "dummy");
        try
        {
            var runner = new ProcessRunner();
            bool opened = runner.OpenFile(tempFile);
            Assert.False(opened);
        }
        finally
        {
            if (File.Exists(tempFile))
            {
                File.Delete(tempFile);
            }
        }
    }

    [Fact]
    public void OpenFile_WhenTrusted_SkipsExtensionRejection()
    {
        var runner = new ProcessRunner();
        Assert.False(runner.OpenFile(string.Empty, isTrusted: true));
        Assert.False(runner.OpenFile(Path.Combine(Path.GetTempPath(), $"missing-{Guid.NewGuid():N}.html"), isTrusted: true));
    }

    [Fact]
    public void SanitizeOutputLine_PreservesPureText_StripsAnsiAndControlChars()
    {
        // 1. 純淨字串應直接返回相同參照（0 配置）
        const string pure = "[Server] Done in 5.2s! For help, type \"help\"";
        string result = ProcessRunner.SanitizeOutputLine(pure);
        Assert.Same(pure, result);

        // 2. ANSI 色碼過濾
        string ansi = "\x1B[32;1m[Server thread/INFO]\x1B[0m: Done (2.1s)!";
        Assert.Equal("[Server thread/INFO]: Done (2.1s)!", ProcessRunner.SanitizeOutputLine(ansi));

        // 3. 控制字元過濾並保留 Tab
        string controlChars = "Hello\x00\x07World\t!";
        Assert.Equal("HelloWorld\t!", ProcessRunner.SanitizeOutputLine(controlChars));

        // 4. 超長字串截斷至 8192
        string longLine = new('A', 10000);
        string truncated = ProcessRunner.SanitizeOutputLine(longLine);
        Assert.Equal(8192, truncated.Length);
    }
}
