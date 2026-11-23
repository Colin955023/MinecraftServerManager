using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class LoaderCompatibilityTests
{
    [Theory]
    [InlineData(LoaderKind.Quilt, "fabric", "1.20.1", true)]
    [InlineData(LoaderKind.Paper, "fabric", "1.20.1", false)]
    [InlineData(LoaderKind.NeoForge, "forge", "1.20.1", true)]
    [InlineData(LoaderKind.NeoForge, "forge", "1.21", false)]
    [InlineData(LoaderKind.NeoForge, "forge", "1.20.10", false)]
    [InlineData(LoaderKind.Fabric, "datapack", "1.21", true)]
    [InlineData(LoaderKind.Fabric, "forge", "1.21", false)]
    [InlineData(LoaderKind.Forge, "forge", "1.21", true)]
    [InlineData(LoaderKind.Unknown, "fabric", "1.21", false)]
    public void IsCompatible_ReturnsExpected(LoaderKind server, string target, string minecraftVersion, bool expected) =>
        Assert.Equal(expected, LoaderCompatibility.IsCompatible(server, [target], minecraftVersion));

    [Fact]
    public void IsCompatible_EmptyTargetList_IsCompatible() =>
        Assert.True(LoaderCompatibility.IsCompatible(LoaderKind.Paper, [], "1.21"));

    [Fact]
    public void GetFallbackLoader_Quilt_ReturnsFabric() =>
        Assert.Equal(LoaderKind.Fabric, LoaderCompatibility.GetFallbackLoader(LoaderKind.Quilt, "1.21"));

    [Fact]
    public void GetFallbackLoader_NeoForgeOn1201_ReturnsForge() =>
        Assert.Equal(LoaderKind.Forge, LoaderCompatibility.GetFallbackLoader(LoaderKind.NeoForge, "1.20.1"));

    [Fact]
    public void GetFallbackLoader_NeoForgeOtherVersion_ReturnsNull() =>
        Assert.Null(LoaderCompatibility.GetFallbackLoader(LoaderKind.NeoForge, "1.21.1"));
}
