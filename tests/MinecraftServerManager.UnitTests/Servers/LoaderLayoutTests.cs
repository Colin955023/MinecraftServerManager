using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class LoaderLayoutTests
{
    [Theory]
    [InlineData(LoaderKind.Forge, "forge-1.20.1-47.2.0.jar", true)]
    [InlineData(LoaderKind.Forge, "forge-1.20.1-47.2.0-installer.jar", false)]
    [InlineData(LoaderKind.NeoForge, "neoforge-20.4.1.jar", true)]
    [InlineData(LoaderKind.NeoForge, "neoforge-20.4.1-INSTALLER.jar", false)]
    [InlineData(LoaderKind.Paper, "paper-1.21.4-164.jar", true)]
    [InlineData(LoaderKind.Paper, "server.jar", false)]
    [InlineData(LoaderKind.Fabric, "fabric-server-launch.jar", true)]
    [InlineData(LoaderKind.Unknown, "paper.jar", false)]
    public void IsLaunchJarName_MatchesPrefixAndInstallerRule(LoaderKind loader, string fileName, bool expected) =>
        Assert.Equal(expected, LoaderLayout.For(loader).IsLaunchJarName(fileName));

    [Fact]
    public void LibraryRelativePath_NeoForge_UsesForwardSlashes() =>
        Assert.Equal("libraries/net/neoforged/neoforge", LoaderLayout.For(LoaderKind.NeoForge).LibraryRelativePath);

    [Fact]
    public void GetLibraryDirectory_Forge_CombinesUnderServerDirectory()
    {
        string root = Path.Combine("srv", "demo");

        Assert.Equal(
            Path.Combine(root, "libraries", "net", "minecraftforge", "forge"),
            LoaderLayout.For(LoaderKind.Forge).GetLibraryDirectory(root));
    }

    [Fact]
    public void IsPaperJarName_VariousNames_MatchesPaperPrefixOnly()
    {
        Assert.True(LoaderLayout.IsPaperJarName("paper-1.21.4-164.jar"));
        Assert.False(LoaderLayout.IsPaperJarName("fabric-server-launch.jar"));
    }
}
