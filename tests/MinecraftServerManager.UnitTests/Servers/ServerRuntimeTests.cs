using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerRuntimeTests : IAsyncLifetime
{
    private readonly TempDirectory _temp = new("msm-runtime-tests-");
    private readonly string _testDir;

    public ServerRuntimeTests() => _testDir = _temp.FullName;

    public ValueTask InitializeAsync()
    {
        File.WriteAllText(Path.Combine(_testDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(_testDir, "run.bat"), "@echo off\n\"C:\\Java\\bin\\java.exe\" -jar server.jar nogui\n");
        return ValueTask.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        _temp.Dispose();
        return ValueTask.CompletedTask;
    }

    private ServerLaunchPlan CreatePlan(string target, string javaPath, int maxMb, int? minMb = null, IReadOnlyList<string>? jvmArgs = null) =>
        TestServerConfigs.CreatePlan("RuntimeTest", _testDir, target, javaPath, maxMb, minMb, jvmArgs);

    [Fact]
    public async Task StartAsync_JarTarget_BuildsJvmArguments()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 4096, 2048, ["-Dfile.encoding=UTF-8"]), TestContext.Current.CancellationToken);

        Assert.True(runtime.IsRunning);
        Assert.Equal(1234, runtime.Pid);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.Equal("java.exe", spec.FileName);
        Assert.Equal(_testDir, spec.WorkingDirectory);
        Assert.Contains("-Xms2048M", spec.Arguments);
        Assert.Contains("-Xmx4096M", spec.Arguments);
        Assert.Contains("-Dfile.encoding=UTF-8", spec.Arguments);
        Assert.Contains("-jar", spec.Arguments);
        Assert.Contains("server.jar", spec.Arguments);
        Assert.Contains("nogui", spec.Arguments);
    }

    [Fact]
    public async Task StartAsync_BatScript_ExecutesDirectly()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("run.bat", "java.exe", 2048), TestContext.Current.CancellationToken);

        Assert.True(runtime.IsRunning);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.Equal(Path.Combine(_testDir, "run.bat"), spec.FileName);
        Assert.Empty(spec.Arguments);
        Assert.Equal(_testDir, spec.WorkingDirectory);
    }

    [Fact]
    public async Task StartAsync_BatScriptWithCustomJava_InjectsJavaHomeAndPath()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        string fakeJava = Path.Combine(_testDir, "custom-jdk", "bin", "java.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(fakeJava)!);
        File.WriteAllText(fakeJava, "dummy");
        await runtime.StartAsync(CreatePlan("run.bat", fakeJava, 2048), TestContext.Current.CancellationToken);

        Assert.True(runtime.IsRunning);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.NotNull(spec.Environment);
        Assert.True(spec.Environment.ContainsKey("JAVA_HOME"));
        Assert.Equal(Path.Combine(_testDir, "custom-jdk"), spec.Environment["JAVA_HOME"]);
        Assert.True(spec.Environment.ContainsKey("PATH"));
        Assert.StartsWith(Path.Combine(_testDir, "custom-jdk", "bin"), spec.Environment["PATH"]!);
    }

    [Fact]
    public async Task StartAsync_AlreadyRunning_Throws()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task SendCommandAsync_Running_WritesAndReturnsTrue()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        bool sent = await runtime.SendCommandAsync("say hello", TestContext.Current.CancellationToken);
        Assert.True(sent);

        var proc = runner.LastCreatedProcess;
        Assert.NotNull(proc);
        Assert.Contains("say hello", proc.WrittenLines);
    }

    [Fact]
    public async Task SendCommandAsync_NotRunning_ReturnsFalse()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        bool sent = await runtime.SendCommandAsync("say hello", TestContext.Current.CancellationToken);
        Assert.False(sent);
    }

    [Fact]
    public async Task OutputLineReceived_ProcessOutput_Forwards()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        var outputs = new List<string>();
        runtime.OutputLineReceived += line => outputs.Add(line);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        runner.LastCreatedProcess!.RaiseOutput("Server started!");

        string item = Assert.Single(outputs);
        Assert.Equal("Server started!", item);
    }

    [Fact]
    public async Task OutputLine_ContainsDone_SetsReady()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        bool readyFired = false;
        runtime.ServerReady += () => readyFired = true;

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);
        Assert.False(runtime.IsReady);

        runner.LastCreatedProcess!.RaiseOutput("[Server thread/INFO]: Preparing spawn area: 98%");
        Assert.False(runtime.IsReady);
        Assert.False(readyFired);

        runner.LastCreatedProcess!.RaiseOutput("[Server thread/INFO]: Done (4.521s)! For help, type \"help\"");
        Assert.True(runtime.IsReady);
        Assert.True(readyFired);
    }

    [Theory]
    [InlineData("[12:00:00 INFO]: Done in 3.2s")]
    [InlineData("[12:00:00 INFO]: DONE IN 3.2s")]
    [InlineData("[Server thread/INFO]: done (1.0s)! For help, type \"help\"")]
    public async Task OutputReady_AnyCaseVariant_FiresServerReadyExactlyOnce(string readyLine)
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);
        int readyCount = 0;
        runtime.ServerReady += () => readyCount++;
        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        runner.LastCreatedProcess!.RaiseOutput(readyLine);
        runner.LastCreatedProcess!.RaiseOutput(readyLine);

        Assert.True(runtime.IsReady);
        Assert.Equal(1, readyCount);
    }

    [Fact]
    public async Task StopAsync_Running_SendsStopAndWaits()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        var result = await runtime.StopAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.Equal(0, result.ExitCode);
        Assert.False(result.WasForceStopped);
        Assert.Contains("stop", runner.LastCreatedProcess!.WrittenLines);
    }

    [Fact]
    public async Task ExitCode_AfterProcessExits_RemainsReadable()
    {
        var runner = new StubProcessRunner(exitCode: 3, interactive: true);
        await using var runtime = new ServerRuntime(runner);
        var exited = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        runtime.ServerExited += code => exited.TrySetResult(code);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);
        await runtime.StopAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);
        int exitCode = await exited.Task.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.NotNull(runtime.ExitCode);
        Assert.Equal(exitCode, runtime.ExitCode);
    }

    [Fact]
    public async Task ProcessExit_Unrequested_ReleasesProcessAndClearsState()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);
        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);
        var process = runner.LastCreatedProcess;
        Assert.NotNull(process);

        // 伺服器自行結束（非由 StopAsync 觸發）
        await process.WriteLineAsync("stop", TestContext.Current.CancellationToken);
        await process.Disposed.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.False(runtime.IsRunning);
        Assert.False(runtime.IsReady);
        Assert.Equal(0, runtime.Pid);
    }

    [Fact]
    public async Task ExitCode_AfterRestart_IsNull()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);
        var exited = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        runtime.ServerExited += code => exited.TrySetResult(code);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);
        await runtime.StopAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);
        await exited.Task.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);
        Assert.NotNull(runtime.ExitCode);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        Assert.Null(runtime.ExitCode);
    }

    [Fact]
    public async Task WaitForExitAsync_WhenTimeout_ReturnsNullAndKeepsRunning()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);
        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);

        var result = await runtime.WaitForExitAsync(TimeSpan.FromMilliseconds(50), TestContext.Current.CancellationToken);

        Assert.Null(result);
        Assert.True(runtime.IsRunning);
    }

    [Fact]
    public async Task WaitForExitAsync_WhenNotRunning_ReturnsLastResult()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        var notStarted = await runtime.WaitForExitAsync(TimeSpan.FromMilliseconds(50), TestContext.Current.CancellationToken);
        Assert.NotNull(notStarted);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024), TestContext.Current.CancellationToken);
        await runtime.SendCommandAsync("stop", TestContext.Current.CancellationToken);
        var result = await runtime.WaitForExitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.NotNull(result);
        Assert.False(result.WasForceStopped);
    }
}
