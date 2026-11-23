using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Java;

namespace MinecraftServerManager.UnitTests.Java;

public sealed class JavaWingetInstallerTests
{
    [Theory]
    [InlineData(8, "Oracle.JavaRuntimeEnvironment")]
    [InlineData(11, "Microsoft.OpenJDK.11")]
    [InlineData(16, "Microsoft.OpenJDK.16")]
    [InlineData(17, "Microsoft.OpenJDK.17")]
    [InlineData(21, "Microsoft.OpenJDK.21")]
    [InlineData(25, "Microsoft.OpenJDK.25")]
    [InlineData(26, "Microsoft.OpenJDK.26")]
    [InlineData(27, "Microsoft.OpenJDK.27")]
    public void ResolvePackageId_SupportedMajor_ReturnsPackageId(int majorVersion, string expectedPackage) =>
        Assert.Equal(expectedPackage, JavaWingetInstaller.ResolvePackageId(majorVersion));

    [Theory]
    [InlineData(7)]
    [InlineData(0)]
    [InlineData(-1)]
    public void ResolvePackageId_UnsupportedMajor_Throws(int unsupportedMajor)
    {
        var ex = Assert.Throws<JavaInstallException>(() =>
            JavaWingetInstaller.ResolvePackageId(unsupportedMajor));

        Assert.Contains(unsupportedMajor.ToString(System.Globalization.CultureInfo.InvariantCulture), ex.Message);
    }

    [Fact]
    public async Task InstallAsync_WingetUnavailable_Throws()
    {
        var runner = new StubProcessRunner(shouldFailStart: true);
        var installer = new JavaWingetInstaller(runner);

        var ex = await Assert.ThrowsAsync<JavaInstallException>(() =>
            installer.InstallWithWingetAsync(21, TestContext.Current.CancellationToken));

        Assert.Contains("無法呼叫 winget 工具", ex.Message);
    }

    [Fact]
    public async Task InstallWithWingetAsync_Success_UsesExactIdAndOfficialSource()
    {
        var specs = new List<ProcessStartSpec>();
        var runner = new StubProcessRunner(spec =>
        {
            specs.Add(spec);
            return new StubManagedProcess(0);
        });
        var installer = new JavaWingetInstaller(runner);

        await installer.InstallWithWingetAsync(21, TestContext.Current.CancellationToken);

        var install = Assert.Single(specs, static s => s.Arguments.Contains("install"));
        Assert.Equal("winget", install.FileName);
        Assert.Equal(
            ["install", "--id", JavaWingetInstaller.ResolvePackageId(21), "--exact", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"],
            install.Arguments);
    }

    [Fact]
    public async Task InstallWithWingetAsync_Canceled_ThrowsOperationCanceledWithoutWrapping()
    {
        var installer = new JavaWingetInstaller(new StubProcessRunner());

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            installer.InstallWithWingetAsync(21, new CancellationToken(canceled: true)));
    }

    [Fact]
    public async Task InstallAsync_InstallFails_ThrowsWithReason()
    {
        // 模擬 install 時 exit code 1602 (0x00000642，使用者取消安裝)
        var runner = new StubProcessRunner(spec =>
            new StubManagedProcess(spec.Arguments.Contains("--version") ? 0 : 1602));
        var installer = new JavaWingetInstaller(runner);

        var ex = await Assert.ThrowsAsync<JavaInstallException>(() =>
            installer.InstallWithWingetAsync(21, TestContext.Current.CancellationToken));

        Assert.Contains("使用者取消安裝", ex.Message);
        Assert.Contains("0x00000642", ex.Message);
    }
}
