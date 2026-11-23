using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.UnitTests.DomainModels;

public sealed class DomainModelTests
{
    [Theory]
    [InlineData("COM1")]
    [InlineData("COM1 .txt")]
    [InlineData("demo.")]
    [InlineData("servers.json")]
    [InlineData("servers_config.json")]
    [InlineData(".msm-delete-test")]
    public void ServerNameParse_WindowsReservedName_Throws(string invalidName) =>
        Assert.Throws<ArgumentException>(() => ServerName.Parse(invalidName));

    [Theory]
    [InlineData("paper", LoaderKind.Paper)]
    [InlineData(" NeoForge ", LoaderKind.NeoForge)]
    [InlineData("VANILLA", LoaderKind.Vanilla)]
    public void LoaderKindsTryParse_DefinedName_ReturnsKind(string value, LoaderKind expected)
    {
        Assert.True(LoaderKinds.TryParse(value, out var kind));
        Assert.Equal(expected, kind);
    }

    [Theory]
    [InlineData("2")]
    [InlineData("-1")]
    [InlineData("spigot")]
    [InlineData("Forge,Fabric")]
    [InlineData("")]
    [InlineData(null)]
    public void LoaderKindsTryParse_NumericOrUnknown_ReturnsUnknown(string? value)
    {
        Assert.False(LoaderKinds.TryParse(value, out var kind));
        Assert.Equal(LoaderKind.Unknown, kind);
        Assert.Equal(LoaderKind.Vanilla, LoaderKinds.ParseOrDefault(value, LoaderKind.Vanilla));
    }

    [Theory]
    [InlineData(LoaderKind.Paper, "paper")]
    [InlineData(LoaderKind.NeoForge, "neoforge")]
    [InlineData(LoaderKind.Quilt, "quilt")]
    public void LoaderKindsModrinthId_KnownKinds_RoundTrips(LoaderKind kind, string id)
    {
        Assert.Equal(id, LoaderKinds.ToModrinthId(kind));
        Assert.True(LoaderKinds.TryParseModrinthId(id.ToUpperInvariant(), out var parsed));
        Assert.Equal(kind, parsed);
    }

    [Theory]
    [InlineData("unknown")]
    [InlineData("datapack")]
    [InlineData("")]
    public void LoaderKindsTryParseModrinthId_NoMapping_ReturnsFalse(string id)
    {
        Assert.False(LoaderKinds.TryParseModrinthId(id, out var kind));
        Assert.Equal(LoaderKind.Unknown, kind);
    }

    [Fact]
    public void OnlineModVersionPrimaryFile_MultipleFiles_PrefersPrimaryJar()
    {
        var version = new OnlineModVersion(
            "id",
            "1.0",
            "範例",
            files: [
                new ModFile("metadata.txt"),
                new ModFile("primary.jar", IsPrimary: true),
                new ModFile("fallback.jar"),
            ]);

        Assert.Equal("primary.jar", version.PrimaryFile?.FileName);
    }

    [Fact]
    public void ServerConfig_SourceListMutated_KeepsCopiedJvmArgs()
    {
        var arguments = new List<string> { "-Xmx2G" };
        var config = new ServerConfig(
            ServerName.Parse("生存伺服器"),
            MinecraftVersion.Parse("1.21.1"),
            LoaderKind.Vanilla,
            "",
            2048,
            jvmArgs: arguments);

        arguments.Add("-Dexample=true");

        Assert.Single(config.JvmArgs);
    }

    [Fact]
    public void ServerCreationPlanCreate_ValidInput_BuildsConfig()
    {
        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("測試計畫伺服器"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Fabric,
            loaderVersion: "0.15.7",
            memoryMaxMb: 4096,
            memoryMinMb: 2048,
            jvmArgs: ["-XX:+UseG1GC"]);

        var config = plan.Config.WithPath(@"C:\Servers\Test");
        Assert.Equal("測試計畫伺服器", config.Name.Value);
        Assert.Equal(4096, config.MemoryMaxMb);
        Assert.Equal(2048, config.MemoryMinMb);
        Assert.Equal(@"C:\Servers\Test", config.Path);
    }

    [Theory]
    [InlineData(2048, 2048, true)]
    [InlineData(4096, 2048, true)]
    [InlineData(1024, 2048, false)]
    public void ServerCreationPlanCreate_InvalidMemory_Throws(int maxMb, int minMb, bool shouldSucceed)
    {
        void act() => _ = ServerCreationPlan.Create(
            ServerName.Parse("MemTest"),
            MinecraftVersion.Parse("1.20.1"),
            LoaderKind.Vanilla,
            memoryMaxMb: maxMb,
            memoryMinMb: minMb);

        if (shouldSucceed)
        {
            act();
        }
        else
        {
            Assert.Throws<ArgumentException>(act);
        }
    }

    [Fact]
    public void OnlineModCompatibilityReport_Errors_DeterminesCompatibility()
    {
        var compatibleReport = new OnlineModCompatibilityReport([], [], [], []);
        Assert.Empty(compatibleReport.HardErrors);
        Assert.False(compatibleReport.HasEnvironmentErrors);

        var incompatibleReport = new OnlineModCompatibilityReport(["遊戲版本不相容", "缺少必要相依"], ["fabric-api"], [], ["遊戲版本不相容"]);
        Assert.NotEmpty(incompatibleReport.HardErrors);
        Assert.True(incompatibleReport.HasEnvironmentErrors);

        var missingOnlyReport = new OnlineModCompatibilityReport(["缺少必要相依"], ["fabric-api"], [], []);
        Assert.False(missingOnlyReport.HasEnvironmentErrors);
    }
}
