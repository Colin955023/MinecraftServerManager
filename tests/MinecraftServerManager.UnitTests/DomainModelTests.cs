using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class DomainModelTests
{
    [Theory]
    [InlineData("COM1")]
    [InlineData("COM1 .txt")]
    [InlineData("demo.")]
    [InlineData("servers.json")]
    [InlineData("servers_config.json")]
    [InlineData(".msm-delete-test")]
    public void ServerNameRejectsWindowsReservedNames(string invalidName) =>
        Assert.Throws<ArgumentException>(() => ServerName.Parse(invalidName));

    [Theory]
    [InlineData("paper", LoaderKind.Paper)]
    [InlineData(" NeoForge ", LoaderKind.NeoForge)]
    [InlineData("VANILLA", LoaderKind.Vanilla)]
    public void LoaderKindsParsesDefinedNames(string value, LoaderKind expected)
    {
        Assert.True(LoaderKinds.TryParse(value, out var kind));
        Assert.Equal(expected, kind);
    }

    [Theory]
    [InlineData("2")]
    [InlineData("-1")]
    [InlineData("spigot")]
    [InlineData("")]
    [InlineData(null)]
    public void LoaderKindsRejectsNumericAndUnknownValues(string? value)
    {
        Assert.False(LoaderKinds.TryParse(value, out var kind));
        Assert.Equal(LoaderKind.Unknown, kind);
        Assert.Equal(LoaderKind.Vanilla, LoaderKinds.ParseOrDefault(value, LoaderKind.Vanilla));
    }

    [Fact]
    public void OnlineModVersionSelectsPrimaryJarBeforeFallback()
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

        Assert.Equal("primary.jar", version.PrimaryFile?.Filename);
    }

    [Fact]
    public void ServerConfigCopiesJvmArguments()
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
    public void ServerCreationPlanBuildsConfig()
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
    public void ServerCreationPlanValidatesMemoryInvariants(int maxMb, int minMb, bool shouldSucceed)
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
    public void OnlineModCompatibilityReportDeterminesCompatibility()
    {
        var compatibleReport = new OnlineModCompatibilityReport([], [], []);
        Assert.Empty(compatibleReport.HardErrors);
        Assert.False(compatibleReport.HasEnvironmentErrors);

        var incompatibleReport = new OnlineModCompatibilityReport(["遊戲版本不相容", "缺少必要相依"], ["fabric-api"], []);
        Assert.NotEmpty(incompatibleReport.HardErrors);
        Assert.True(incompatibleReport.HasEnvironmentErrors);
    }
}

