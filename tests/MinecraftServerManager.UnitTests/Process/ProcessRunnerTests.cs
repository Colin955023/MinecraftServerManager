using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Process;

namespace MinecraftServerManager.UnitTests.Process;

public sealed class ProcessRunnerTests
{
    [Fact]
    public async Task StartAsync_Executable_CapturesOutputWithoutShell()
    {
        var runner = new ProcessRunner();
        var output = new List<ProcessOutput>();
        await using var process = await runner.StartAsync(new ProcessStartSpec(
            "dotnet",
            ["--version"]), cancellationToken: TestContext.Current.CancellationToken);
        process.OutputReceived += output.Add;

        var result = await process.WaitForExitAsync(TestContext.Current.CancellationToken);

        Assert.True(process.Pid > 0);
        Assert.Equal(0, result.ExitCode);
        Assert.False(result.WasForceStopped);
        Assert.Contains(output, static item => item.Kind == ProcessOutputKind.StandardOutput);
    }

    [Fact]
    public async Task StartAsync_MissingAbsoluteExecutable_Rejects()
    {
        using var temp = new TempDirectory("msm-proc-missing-");
        var runner = new ProcessRunner();

        await Assert.ThrowsAsync<FileNotFoundException>(() => runner.StartAsync(new ProcessStartSpec(
            temp.Combine("nonexistent", "missing.exe"),
            []), cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task StartAsync_EmptyExecutable_Rejects()
    {
        var runner = new ProcessRunner();

        await Assert.ThrowsAsync<ArgumentException>(() => runner.StartAsync(new ProcessStartSpec(
            "   ",
            []), cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task StartAsync_MissingWorkingDirectory_Rejects()
    {
        using var temp = new TempDirectory("msm-proc-cwd-");
        var runner = new ProcessRunner();

        await Assert.ThrowsAsync<DirectoryNotFoundException>(() => runner.StartAsync(new ProcessStartSpec(
            "dotnet",
            ["--version"],
            WorkingDirectory: temp.Combine("nonexistent")), cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task StartAsync_BatchScriptPathWithSpaces_CapturesOutput()
    {
        using var tempDirTemp = new TempDirectory("msm test batch ");
        string tempDir = tempDirTemp.CreateSubdirectory("root");
        string batPath = Path.Combine(tempDir, "script with space.bat");
        File.WriteAllText(batPath, "@echo off\r\necho BATCH_OUTPUT_%1\r\n");

        var runner = new ProcessRunner();
        var output = new List<ProcessOutput>();

        await using var process = await runner.StartAsync(new ProcessStartSpec(
            batPath,
            ["TEST_ARG"],
            WorkingDirectory: tempDir), cancellationToken: TestContext.Current.CancellationToken);
        process.OutputReceived += output.Add;

        var result = await process.WaitForExitAsync(TestContext.Current.CancellationToken);

        Assert.True(process.Pid > 0);
        Assert.Equal(0, result.ExitCode);
        Assert.False(result.WasForceStopped);
        Assert.Contains(output, static item => item.Text.Contains("BATCH_OUTPUT_TEST_ARG", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData("A & calc", "run.bat", "nogui")]
    [InlineData("safe", "run.bat", "%PATH%")]
    [InlineData("safe", "run.bat", "a|b")]
    public async Task StartAsync_BatchArgumentWithMetaCharacters_Rejects(string folderName, string scriptName, string argument)
    {
        using var tempDirTemp = new TempDirectory("msm-meta-");
        string tempDir = Path.Combine(tempDirTemp.FullName, folderName);
        Directory.CreateDirectory(tempDir);

        string batPath = Path.Combine(tempDir, scriptName);
        File.WriteAllText(batPath, "@echo off\r\n");

        await Assert.ThrowsAsync<ArgumentException>(() => new ProcessRunner().StartAsync(new ProcessStartSpec(batPath, [argument], WorkingDirectory: tempDir), cancellationToken: TestContext.Current.CancellationToken));
    }

    [Fact]
    public void SanitizeOutputLine_PreservesPureText_StripsAnsiAndControlChars()
    {
        // 1. 純淨字串應直接傳回相同參照（0 配置）
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

    [Fact]
    public async Task OutputSubscribe_LateSubscriber_ReceivesBacklogInOrder()
    {
        const int lineCount = 200;
        var runner = new ProcessRunner();
        await using var process = await runner.StartAsync(new ProcessStartSpec(
            "cmd.exe",
            ["/d", "/c", $"for /L %i in (1,1,{lineCount}) do @echo %i"]), cancellationToken: TestContext.Current.CancellationToken);

        // 延後訂閱，讓部分輸出先進入積壓佇列。
        // 注意：此為時間式設定（非負向斷言），無法以行程結束當作確定性訊號，因為目標是驗證「執行中」的積壓；
        // 即使輸出已全部完成，積壓行為仍成立，故 200 ms 僅為讓部分輸出先到達的寬鬆下限。
        await Task.Delay(200, TestContext.Current.CancellationToken);

        var received = new List<int>();
        int active = 0;
        bool overlapped = false;
        process.OutputReceived += item =>
        {
            if (Interlocked.Increment(ref active) > 1)
            {
                overlapped = true;
            }

            if (int.TryParse(item.Text, out int value))
            {
                received.Add(value);
            }

            Thread.SpinWait(2000);
            Interlocked.Decrement(ref active);
        };

        await process.WaitForExitAsync(TestContext.Current.CancellationToken);

        Assert.False(overlapped);
        Assert.Equal(Enumerable.Range(1, lineCount), received);
    }

    [Fact]
    public async Task OutputLineObserved_ReceivesReadyMarkerEvenWhenDisplayBacklogDropsLines()
    {
        using var temp = new TempDirectory("msm-proc-output-flood-");
        string script = Path.Combine(temp.FullName, "flood.bat");
        File.WriteAllText(script, "@echo off\r\nfor /L %%i in (1,1,1200) do echo flood-%%i\r\necho Done (1s)\r\n");

        var observed = new System.Collections.Concurrent.ConcurrentQueue<ProcessOutput>();
        var runner = new ProcessRunner();
        IManagedProcess process = await runner.StartAsync(
            new ProcessStartSpec(script, [], WorkingDirectory: temp.FullName),
            observed.Enqueue,
            cancellationToken: TestContext.Current.CancellationToken);

        await process.WaitForExitAsync(TestContext.Current.CancellationToken);
        await process.DisposeAsync();

        Assert.Contains(observed, static item => item.Text.Contains("Done (", StringComparison.Ordinal));
        Assert.True(process.DroppedOutputLines > 0);
    }

    [Fact]
    public void GetStartTimeUtc_CurrentAndMissingPid_ReturnsValueOrNull()
    {
        var runner = new ProcessRunner();

        Assert.NotNull(runner.GetStartTimeUtc(Environment.ProcessId));
        Assert.Null(runner.GetStartTimeUtc(int.MaxValue));
    }
}
