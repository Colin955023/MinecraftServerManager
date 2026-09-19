using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Java;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class JavaWingetInstallerTests
{
    [Theory]
    [InlineData(8, "Oracle.JavaRuntimeEnvironment")]
    [InlineData(11, "Microsoft.OpenJDK.11")]
    [InlineData(16, "Microsoft.OpenJDK.16")]
    [InlineData(17, "Microsoft.OpenJDK.17")]
    [InlineData(21, "Microsoft.OpenJDK.21")]
    [InlineData(25, "Microsoft.OpenJDK.25")]
    public void ResolvesCorrectWingetPackageId(int majorVersion, string expectedPackage) => Assert.Equal(expectedPackage, JavaWingetInstaller.ResolvePackageId(majorVersion));

    [Theory]
    [InlineData(7)]
    [InlineData(9)]
    [InlineData(10)]
    [InlineData(18)]
    public void ThrowsForUnsupportedJavaMajorVersion(int unsupportedMajor)
    {
        var ex = Assert.Throws<JavaInstallException>(() =>
            JavaWingetInstaller.ResolvePackageId(unsupportedMajor));

        Assert.Contains(unsupportedMajor.ToString(System.Globalization.CultureInfo.InvariantCulture), ex.Message);
    }

    [Fact]
    public async Task ThrowsWhenWingetIsNotAvailable()
    {
        var runner = new MockProcessRunner(shouldFailStart: true);
        var installer = new JavaWingetInstaller(runner);

        var ex = await Assert.ThrowsAsync<JavaInstallException>(() =>
            installer.InstallWithWingetAsync(21));

        Assert.Contains("無法呼叫 winget 工具", ex.Message);
    }

    [Fact]
    public async Task ThrowsWithDetailedReasonOnFailedInstall()
    {
        // 模擬 install 時 exit code 1602 (使用者取消安裝)
        var runner = new MockProcessRunner(installExitCode: 1602);
        var installer = new JavaWingetInstaller(runner);

        var ex = await Assert.ThrowsAsync<JavaInstallException>(() =>
            installer.InstallWithWingetAsync(21));

        Assert.Contains("使用者取消安裝", ex.Message);
        Assert.Equal(1602, ex.ExitCode);
    }

    private sealed class MockProcessRunner(
        int installExitCode = 0,
        bool shouldFailStart = false) : IProcessRunner
    {
        public Task<IManagedProcess> StartAsync(ProcessStartSpec specification, CancellationToken cancellationToken = default)
        {
            if (shouldFailStart)
            {
                throw new FileNotFoundException("找不到 winget");
            }

            bool isVersionCheck = specification.Arguments.Contains("--version");
            int code = isVersionCheck ? 0 : installExitCode;
            return Task.FromResult<IManagedProcess>(new MockManagedProcess(code));
        }
    }

    private sealed class MockManagedProcess(int exitCode) : IManagedProcess
    {
        public int Pid => 9999;
        public bool HasExited => true;
        public int? ExitCode => exitCode;

        public event Action<ProcessOutput>? OutputReceived
        {
            add { }
            remove { }
        }

        public Task WriteLineAsync(string line, CancellationToken cancellationToken = default) => Task.CompletedTask;

        public Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new ProcessExitResult(exitCode, false));

        public Task<ProcessExitResult> StopAsync(TimeSpan gracefulTimeout, CancellationToken cancellationToken = default) =>
            Task.FromResult(new ProcessExitResult(exitCode, false));

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
