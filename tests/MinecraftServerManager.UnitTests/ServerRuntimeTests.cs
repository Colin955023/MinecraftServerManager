using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerRuntimeTests : IDisposable
{
    private readonly string _testDir;

    public ServerRuntimeTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm-runtime-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
    }

    public void Dispose()
    {
        for (int i = 0; i < 3; i++)
        {
            try
            {
                if (Directory.Exists(_testDir))
                {
                    Directory.Delete(_testDir, recursive: true);
                }
                break;
            }
            catch (Exception) when (i < 2)
            {
                Thread.Sleep(50);
            }
            catch
            {
            }
        }
    }

    [Fact]
    public async Task StartAsyncWithJarBuildsCorrectJvmArguments()
    {
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(
            javaExecutablePath: "java.exe",
            serverDirectory: _testDir,
            executableName: "server.jar",
            memoryMaxMb: 4096,
            memoryMinMb: 2048,
            customJvmArgs: ["-Dfile.encoding=UTF-8"]);

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
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync(
            javaExecutablePath: "java.exe",
            serverDirectory: _testDir,
            executableName: "run.bat",
            memoryMaxMb: 2048);

        Assert.True(runtime.IsRunning);

        var spec = runner.LastSpecification;
        Assert.NotNull(spec);
        Assert.Equal(Path.Combine(_testDir, "run.bat"), spec.FileName);
        Assert.Empty(spec.Arguments);
        Assert.Equal(_testDir, spec.WorkingDirectory);
    }

    [Fact]
    public async Task StartAsyncWhenAlreadyRunningThrowsInvalidOperationException()
    {
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync("java.exe", _testDir, "server.jar", 1024);

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            runtime.StartAsync("java.exe", _testDir, "server.jar", 1024));
    }

    [Fact]
    public async Task SendCommandAsyncWritesToProcessReturnsTrueWhenRunning()
    {
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync("java.exe", _testDir, "server.jar", 1024);

        bool sent = await runtime.SendCommandAsync("say hello");
        Assert.True(sent);

        var proc = runner.LastCreatedProcess;
        Assert.NotNull(proc);
        Assert.Contains("say hello", proc.WrittenLines);
    }

    [Fact]
    public async Task SendCommandAsyncReturnsFalseWhenNotRunning()
    {
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        bool sent = await runtime.SendCommandAsync("say hello");
        Assert.False(sent);
    }

    [Fact]
    public async Task OutputLineReceivedForwardsOutputFromProcess()
    {
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        var outputs = new List<string>();
        runtime.OutputLineReceived += line => outputs.Add(line);

        await runtime.StartAsync("java.exe", _testDir, "server.jar", 1024);

        runner.LastCreatedProcess!.RaiseOutput("Server started!");

        Assert.Single(outputs);
        Assert.Equal("Server started!", outputs[0]);
    }

    [Fact]
    public async Task StopAsyncSendsStopCommandAndWaitsForExit()
    {
        var runner = new FakeProcessRunner();
        await using var runtime = new ServerRuntime(runner);

        await runtime.StartAsync("java.exe", _testDir, "server.jar", 1024);

        var result = await runtime.StopAsync(TimeSpan.FromSeconds(5));

        Assert.Equal(0, result.ExitCode);
        Assert.False(result.WasForceStopped);
        Assert.Contains("stop", runner.LastCreatedProcess!.WrittenLines);
    }

    private sealed class FakeProcessRunner : IProcessRunner
    {
        public ProcessStartSpec? LastSpecification { get; private set; }
        public FakeManagedProcess? LastCreatedProcess { get; private set; }

        public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default)
        {
            LastSpecification = specification;
            LastCreatedProcess = new FakeManagedProcess();
            return Task.FromResult<IManagedProcess>(LastCreatedProcess);
        }
    }

    private sealed class FakeManagedProcess : IManagedProcess
    {
        private readonly TaskCompletionSource<ProcessExitResult> _exitTcs = new();

        public int Pid => 1234;
        public bool HasExited { get; private set; }
        public int? ExitCode => HasExited ? 0 : null;
        public List<string> WrittenLines { get; } = [];

        public event Action<ProcessOutput>? OutputReceived;

        public void RaiseOutput(string line) => OutputReceived?.Invoke(new ProcessOutput(ProcessOutputKind.StandardOutput, line));

        public Task WriteLineAsync(string line, CancellationToken cancellationToken = default)
        {
            WrittenLines.Add(line);
            if (line == "stop")
            {
                HasExited = true;
                _exitTcs.TrySetResult(new ProcessExitResult(0, false));
            }
            return Task.CompletedTask;
        }

        public async Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default)
        {
            if (cancellationToken.CanBeCanceled)
            {
                await using (cancellationToken.Register(() => _exitTcs.TrySetCanceled(cancellationToken)))
                {
                    return await _exitTcs.Task.ConfigureAwait(false);
                }
            }

            return await _exitTcs.Task.ConfigureAwait(false);
        }

        public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default)
        {
            HasExited = true;
            _exitTcs.TrySetResult(new ProcessExitResult(-1, true));
            return Task.FromResult(new ProcessExitResult(-1, true));
        }

        public ValueTask DisposeAsync()
        {
            HasExited = true;
            return ValueTask.CompletedTask;
        }
    }
}
