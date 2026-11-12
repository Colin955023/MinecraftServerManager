using MinecraftServerManager.Core.Errors;
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
    [InlineData(26, "Microsoft.OpenJDK.26")]
    [InlineData(27, "Microsoft.OpenJDK.27")]
    public void ResolvesCorrectWingetPackageId(int majorVersion, string expectedPackage) =>
        Assert.Equal(expectedPackage, JavaWingetInstaller.ResolvePackageId(majorVersion));

    [Theory]
    [InlineData(7)]
    [InlineData(0)]
    [InlineData(-1)]
    public void ThrowsForUnsupportedJavaMajorVersion(int unsupportedMajor)
    {
        var ex = Assert.Throws<JavaInstallException>(() =>
            JavaWingetInstaller.ResolvePackageId(unsupportedMajor));

        Assert.Contains(unsupportedMajor.ToString(System.Globalization.CultureInfo.InvariantCulture), ex.Message);
    }

    [Fact]
    public async Task ThrowsWhenWingetIsNotAvailable()
    {
        var runner = new StubProcessRunner(shouldFailStart: true);
        var installer = new JavaWingetInstaller(runner);

        var ex = await Assert.ThrowsAsync<JavaInstallException>(() =>
            installer.InstallWithWingetAsync(21));

        Assert.Contains("無法呼叫 winget 工具", ex.Message);
    }

    [Fact]
    public async Task ThrowsWithDetailedReasonOnFailedInstall()
    {
        // 模擬 install 時 exit code 1602 (0x00000642，使用者取消安裝)
        var runner = new StubProcessRunner(spec =>
            new StubManagedProcess(spec.Arguments.Contains("--version") ? 0 : 1602));
        var installer = new JavaWingetInstaller(runner);

        var ex = await Assert.ThrowsAsync<JavaInstallException>(() =>
            installer.InstallWithWingetAsync(21));

        Assert.Contains("使用者取消安裝", ex.Message);
        Assert.Contains("0x00000642", ex.Message);
    }
}
