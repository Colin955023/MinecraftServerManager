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
        Assert.Contains(output, item => item.Kind == ProcessOutputKind.StandardOutput);
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
            Assert.Contains(output, item => item.Text.Contains("BATCH_OUTPUT_TEST_ARG", StringComparison.Ordinal));
        }
        finally
        {
            if (Directory.Exists(tempDir))
            {
                Directory.Delete(tempDir, recursive: true);
            }
        }
    }
}
