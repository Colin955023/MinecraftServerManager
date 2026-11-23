using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerSetupHelpersTests : IDisposable
{
    private readonly TempDirectory _dir = new("msm-unittest-setup-");

    public void Dispose() => _dir.Dispose();

    [Fact]
    public void CleanupRedundantStartupScripts_KnownStems_DeletesOnlyRedundantScripts()
    {
        string[] removed = ["start.bat", "run.cmd", "Launch.ps1", "server.sh"];
        string[] kept = [ServerDefaults.StartServerBatFileName, ServerDefaults.StartServerBatFileName + ".bak", "custom.bat", "start.txt", "eula.txt"];
        foreach (string name in removed.Concat(kept))
        {
            File.WriteAllText(_dir.Combine(name), "x");
        }

        Directory.CreateDirectory(_dir.Combine("run.bat"));

        ServerSetupHelpers.CleanupRedundantStartupScripts(_dir);

        Assert.All(removed, name => Assert.False(File.Exists(_dir.Combine(name)), name));
        Assert.All(kept, name => Assert.True(File.Exists(_dir.Combine(name)), name));
        Assert.True(Directory.Exists(_dir.Combine("run.bat")));
    }

    [Fact]
    public void CleanupRedundantStartupScripts_MissingDirectory_DoesNothing() =>
        Assert.Null(Record.Exception(() => ServerSetupHelpers.CleanupRedundantStartupScripts(_dir.Combine("missing"))));

    [Fact]
    public void CreateConfigFromInspection_ValidInspection_MapsFields()
    {
        var inspection = new ServerInspection
        {
            Path = _dir,
            MinecraftVersion = MinecraftVersion.Parse("1.21.1"),
            LoaderVersion = "0.16.5",
            MemoryMaxMb = 4096,
            MemoryMinMb = 1024,
        };

        ServerConfig config = ServerSetupHelpers.CreateConfigFromInspection(ServerName.Parse("demo"), LoaderKind.Fabric, inspection, _dir);

        Assert.Equal(MinecraftVersion.Parse("1.21.1"), config.MinecraftVersion);
        Assert.Equal(LoaderKind.Fabric, config.LoaderType);
        Assert.Equal("0.16.5", config.LoaderVersion);
        Assert.Equal(4096, config.MemoryMaxMb);
        Assert.Equal(1024, config.MemoryMinMb);
    }

    [Theory]
    [InlineData(0, 512, ServerDefaults.DefaultMemoryMaxMb, 512)]
    [InlineData(1024, 2048, 1024, null)]
    [InlineData(2048, 0, 2048, null)]
    public void CreateConfigFromInspection_MemoryEdgeCases_NormalizesValues(int max, int min, int expectedMax, int? expectedMin)
    {
        var inspection = new ServerInspection
        {
            Path = _dir,
            MinecraftVersion = MinecraftVersion.Parse("1.20.4"),
            MemoryMaxMb = max,
            MemoryMinMb = min,
        };

        ServerConfig config = ServerSetupHelpers.CreateConfigFromInspection(ServerName.Parse("demo"), LoaderKind.Vanilla, inspection, _dir);

        Assert.Equal(expectedMax, config.MemoryMaxMb);
        Assert.Equal(expectedMin, config.MemoryMinMb);
        Assert.Equal(ServerDefaults.UnknownLoaderVersion, config.LoaderVersion);
    }

    [Fact]
    public void CreateConfigFromInspection_UnknownVersion_Throws()
    {
        var inspection = new ServerInspection { Path = _dir };

        var ex = Assert.Throws<InvalidOperationException>(() =>
            ServerSetupHelpers.CreateConfigFromInspection(ServerName.Parse("demo"), LoaderKind.Vanilla, inspection, _dir));
        Assert.Equal(ServerSetupHelpers.UnknownVersionMessage, ex.Message);
    }

    [Fact]
    public void ResolveServerDirectory_ExistingChild_ReturnsChildDirectory()
    {
        string expected = Directory.CreateDirectory(_dir.Combine("alpha")).FullName;

        Assert.Equal(expected, ServerSetupHelpers.ResolveServerDirectory(_dir, "alpha"));
    }

    [Theory]
    [InlineData(".")]
    [InlineData("..")]
    [InlineData("a\\b")]
    [InlineData("a/b")]
    [InlineData("C:\\abs")]
    [InlineData(" ")]
    public void ResolveServerDirectory_InvalidName_Throws(string name) =>
        Assert.ThrowsAny<ArgumentException>(() => ServerSetupHelpers.ResolveServerDirectory(_dir, name));

    [Fact]
    public void CheckFreeSpace_ZeroRequirement_ReturnsNull() =>
        Assert.Null(ServerSetupHelpers.CheckFreeSpace(_dir, 0));

    [Fact]
    public void CheckFreeSpace_HugeRequirement_ReturnsMessage()
    {
        string? message = ServerSetupHelpers.CheckFreeSpace(_dir, long.MaxValue);

        Assert.NotNull(message);
        Assert.Contains("可用空間不足", message, StringComparison.Ordinal);
    }
}
