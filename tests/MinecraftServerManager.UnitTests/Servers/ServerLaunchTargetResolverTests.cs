using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerLaunchTargetResolverTests : IDisposable
{
    private readonly TempDirectory _dir = new("msm-unittest-launch-");

    public void Dispose() => _dir.Dispose();

    private void Touch(params string[] parts)
    {
        string path = _dir.Combine(parts);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, "x");
    }

    private string Resolve(LoaderKind loader = LoaderKind.Unknown) =>
        ServerLaunchTargetResolver.ResolveLaunchTarget(_dir, loader);

    [Fact]
    public void ResolveLaunchTarget_RunBatReferencesExistingArgsFile_ReturnsArgsReference()
    {
        Touch("libraries", "custom", "win_args.txt");
        File.WriteAllText(_dir.Combine("run.bat"), "java @user_jvm_args.txt @libraries\\custom\\win_args.txt %*");

        Assert.Equal("@libraries/custom/win_args.txt", Resolve());
    }

    [Fact]
    public void ResolveLaunchTarget_RunBatArgsOutsideServer_FallsBackToJar()
    {
        File.WriteAllText(_dir.Combine("run.bat"), "java @..\\outside\\win_args.txt");
        Touch("server.jar");

        Assert.Equal("server.jar", Resolve());
    }

    [Fact]
    public void ResolveLaunchTarget_MultipleLibraryVersions_ReturnsNewestWinArgs()
    {
        Touch("libraries", "net", "neoforged", "neoforge", "21.1.9", "win_args.txt");
        Touch("libraries", "net", "neoforged", "neoforge", "21.1.10", "win_args.txt");

        Assert.Equal("@libraries/net/neoforged/neoforge/21.1.10/win_args.txt", Resolve());
    }

    [Theory]
    [InlineData(LoaderKind.Fabric, "fabric-server-launch.jar")]
    [InlineData(LoaderKind.Forge, "forge-1.20.1.jar")]
    [InlineData(LoaderKind.Paper, "paper-1.21.jar")]
    public void ResolveLaunchTarget_LoaderSpecified_PrefersLoaderJar(LoaderKind loader, string expected)
    {
        Touch("server.jar");
        Touch("forge-1.20.1-installer.jar");
        Touch("forge-1.20.1.jar");
        Touch("fabric-server-launch.jar");
        Touch("paper-1.21.jar");

        Assert.Equal(expected, Resolve(loader));
    }

    [Fact]
    public void ResolveLaunchTarget_NoLoader_PrefersPaperThenStandardCandidates()
    {
        Touch("minecraft_server.jar");
        Touch("server.jar");

        Assert.Equal("server.jar", Resolve());

        Touch("paper-1.21.jar");
        Assert.Equal("paper-1.21.jar", Resolve());
    }

    [Fact]
    public void ResolveLaunchTarget_OnlyInstallerAndOtherJars_SkipsInstaller()
    {
        Touch("aaa-installer.jar");
        Touch("custom.jar");

        Assert.Equal("custom.jar", Resolve());
    }

    [Fact]
    public void ResolveLaunchTarget_NoJarWithRunBat_ReturnsRunBat()
    {
        File.WriteAllText(_dir.Combine("run.bat"), "echo no args");

        Assert.Equal("run.bat", Resolve());
    }

    [Fact]
    public void ResolveLaunchTarget_EmptyDirectory_ReturnsDefaultServerJar() =>
        Assert.Equal("server.jar", Resolve());

    [Fact]
    public void ResolveLaunchTarget_BlankDirectory_Throws() =>
        Assert.Throws<ArgumentException>(() => ServerLaunchTargetResolver.ResolveLaunchTarget(" "));
}
