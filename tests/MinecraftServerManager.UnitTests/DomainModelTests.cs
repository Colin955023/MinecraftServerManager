using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class DomainModelTests
{
    [Fact]
    public void ServerNameRejectsWindowsReservedNames()
    {
        Assert.Throws<ArgumentException>(static () => ServerName.Parse("COM1"));
        Assert.Throws<ArgumentException>(static () => ServerName.Parse("COM1 .txt"));
        Assert.Throws<ArgumentException>(static () => ServerName.Parse("demo."));
        Assert.Throws<ArgumentException>(static () => ServerName.Parse("servers.json"));
        Assert.Throws<ArgumentException>(static () => ServerName.Parse("servers_config.json"));
        Assert.Throws<ArgumentException>(static () => ServerName.Parse(".msm-delete-test"));
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
    public void LoaderVersionPreservesStableAndGameVersionMetadata()
    {
        var version = new Core.Loaders.LoaderVersion("0.16.10", Stable: true, MinecraftVersion: "1.21.1", CompatibleGameVersions: ["1.21.1"]);

        Assert.True(version.Stable);
        Assert.Equal("1.21.1", version.CompatibleGameVersions?.Single());
    }

    [Fact]
    public void ServerOperationResultFactoryMethodsProduceCorrectState()
    {
        var ok = ServerOperationResult.Ok("成功啟動", "通知", "測試伺服器");
        Assert.True(ok.Success);
        Assert.False(ok.Failed);
        Assert.Equal("成功啟動", ok.Message);
        Assert.Equal("測試伺服器", ok.ServerName);

        var fail = ServerOperationResult.Fail("磁碟空間不足", "錯誤", "測試伺服器");
        Assert.False(fail.Success);
        Assert.True(fail.Failed);
    }

    [Fact]
    public void ServerCreationPlanValidatesInvariantsAndBuildsConfig()
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

        // 驗證不變條件：min > max 應擲出 ArgumentException
        Assert.Throws<ArgumentException>(static () => ServerCreationPlan.Create(
            ServerName.Parse("無效"),
            MinecraftVersion.Parse("1.20.1"),
            LoaderKind.Vanilla,
            memoryMaxMb: 1024,
            memoryMinMb: 2048));
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
    public void ServerImportResultFactoryMethodsProduceExpectedStates()
    {
        var success = ServerImportResult.Success("server1", new ServerConfig(ServerName.Parse("server1"), MinecraftVersion.Parse("1.20.1"), LoaderKind.Vanilla, "", 2048));
        var failed = ServerImportResult.Failed("server3", "檔案損毀");

        Assert.True(success.Completed);
        Assert.False(failed.Completed);
        Assert.Equal("檔案損毀", failed.Message);
    }

    [Fact]
    public void OnlineModCompatibilityReportDeterminesCompatibility()
    {
        var compatibleReport = new OnlineModCompatibilityReport([], [], []);
        Assert.True(compatibleReport.IsCompatible);

        var incompatibleReport = new OnlineModCompatibilityReport(["遊戲版本不相容"], ["fabric-api"], []);
        Assert.False(incompatibleReport.IsCompatible);
    }
}

