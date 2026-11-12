using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

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
        new ServerLaunchPlanner().CreatePlan(
            new ServerConfig(ServerName.Parse("RuntimeTest"), MinecraftVersion.Parse("1.21.4"), LoaderKind.Vanilla, string.Empty, maxMb, minMb, path: _testDir, jvmArgs: jvmArgs),
            target,
            javaPath);

    [Fact]
    public async Task StartAsyncWithJarBuildsCorrectJvmArguments()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 4096, 2048, ["-Dfile.encoding=UTF-8"]));

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
    public async Task StartAsyncWithBatScriptExecutesScriptDirectly()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("run.bat", "java.exe", 2048));

        Assert.True(runtime.IsRunning);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.Equal(Path.Combine(_testDir, "run.bat"), spec.FileName);
        Assert.Empty(spec.Arguments);
        Assert.Equal(_testDir, spec.WorkingDirectory);
    }

    [Fact]
    public async Task StartAsyncWithBatScriptAndCustomJavaInjectsJavaHomeAndPathEnvironment()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        string fakeJava = Path.Combine(_testDir, "custom-jdk", "bin", "java.exe");
        await runtime.StartAsync(CreatePlan("run.bat", fakeJava, 2048));

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
    public async Task StartAsyncWhenAlreadyRunningThrowsInvalidOperationException()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024)));
    }

    [Fact]
    public async Task SendCommandAsyncWritesToProcessReturnsTrueWhenRunning()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));

        bool sent = await runtime.SendCommandAsync("say hello");
        Assert.True(sent);

        var proc = runner.LastCreatedProcess;
        Assert.NotNull(proc);
        Assert.Contains("say hello", proc.WrittenLines);
    }

    [Fact]
    public async Task SendCommandAsyncReturnsFalseWhenNotRunning()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        bool sent = await runtime.SendCommandAsync("say hello");
        Assert.False(sent);
    }

    [Fact]
    public async Task OutputLineReceivedForwardsOutputFromProcess()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        var outputs = new List<string>();
        runtime.OutputLineReceived += line => outputs.Add(line);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));

        runner.LastCreatedProcess!.RaiseOutput("Server started!");

        string item = Assert.Single(outputs);
        Assert.Equal("Server started!", item);
    }

    [Fact]
    public async Task OutputContainingDoneTriggersServerReadyAndSetsIsReady()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        bool readyFired = false;
        runtime.ServerReady += () => readyFired = true;

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));
        Assert.False(runtime.IsReady);

        runner.LastCreatedProcess!.RaiseOutput("[Server thread/INFO]: Preparing spawn area: 98%");
        Assert.False(runtime.IsReady);
        Assert.False(readyFired);

        runner.LastCreatedProcess!.RaiseOutput("[Server thread/INFO]: Done (4.521s)! For help, type \"help\"");
        Assert.True(runtime.IsReady);
        Assert.True(readyFired);
    }

    [Fact]
    public async Task StopAsyncSendsStopCommandAndWaitsForExit()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));

        var result = await runtime.StopAsync(TimeSpan.FromSeconds(5));

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

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));
        await runtime.StopAsync(TimeSpan.FromSeconds(5));
        int exitCode = await exited.Task.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.NotNull(runtime.ExitCode);
        Assert.Equal(exitCode, runtime.ExitCode);
    }

    [Fact]
    public async Task ExitCode_AfterRestart_IsNull()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);
        var exited = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        runtime.ServerExited += code => exited.TrySetResult(code);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));
        await runtime.StopAsync(TimeSpan.FromSeconds(5));
        await exited.Task.WaitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);
        Assert.NotNull(runtime.ExitCode);

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));

        Assert.Null(runtime.ExitCode);
    }

    [Fact]
    public async Task WaitForExitAsync_WhenTimeout_ReturnsNullAndKeepsRunning()
    {
        var runner = new StubProcessRunner(interactive: true);
        await using var runtime = new ServerRuntime(runner);
        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));

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

        await runtime.StartAsync(CreatePlan("server.jar", "java.exe", 1024));
        await runtime.SendCommandAsync("stop", TestContext.Current.CancellationToken);
        var result = await runtime.WaitForExitAsync(TimeSpan.FromSeconds(5), TestContext.Current.CancellationToken);

        Assert.NotNull(result);
        Assert.False(result.WasForceStopped);
    }
}
