using MinecraftServerManager.Domain.Loaders;
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
        Assert.Throws<ArgumentException>(() => ServerName.Parse("COM1"));
        Assert.Throws<ArgumentException>(() => ServerName.Parse("COM1 .txt"));
        Assert.Throws<ArgumentException>(() => ServerName.Parse("demo."));
        Assert.Throws<ArgumentException>(() => ServerName.Parse("servers_config.json"));
        Assert.Throws<ArgumentException>(() => ServerName.Parse(".msm-delete-test"));
    }

    [Fact]
    public void ProgressEventClampsPhasePercent()
    {
        var progress = new ProgressEvent("download", "完成", 12, 10);

        Assert.Equal(100, progress.PhasePercent);
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
        var version = new LoaderVersion("0.16.10", stable: true, minecraftVersion: "1.21.1", gameVersions: ["1.21.1"]);

        Assert.True(version.Stable);
        Assert.Equal("1.21.1", version.GameVersions.Single());
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
        var plan = new ServerCreationPlan(
            transactionId: "tx-12345",
            name: ServerName.Parse("測試計畫伺服器"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Fabric,
            loaderVersion: "0.15.7",
            memoryMaxMb: 4096,
            memoryMinMb: 2048,
            jvmArgs: ["-XX:+UseG1GC"],
            properties: [new KeyValuePair<string, string>("difficulty", "hard")],
            finalPath: @"C:\Servers\Test",
            stagingPath: @"C:\Temp\Test",
            warnings: [new ServerCreationWarning("建議升級記憶體")]
        );

        Assert.Single(plan.Warnings);
        var config = plan.BuildConfig(@"C:\Servers\Test");
        Assert.Equal("測試計畫伺服器", config.Name.Value);
        Assert.Equal(4096, config.MemoryMaxMb);
        Assert.Equal(2048, config.MemoryMinMb);
        Assert.Equal(@"C:\Servers\Test", config.Path);

        // 驗證不變量：min > max 應拋出 ArgumentException
        Assert.Throws<ArgumentException>(() => new ServerCreationPlan(
            "tx-fail",
            ServerName.Parse("無效"),
            MinecraftVersion.Parse("1.20.1"),
            LoaderKind.Vanilla,
            "",
            memoryMaxMb: 1024,
            memoryMinMb: 2048,
            jvmArgs: [],
            properties: [],
            finalPath: "",
            stagingPath: ""
        ));
    }

    [Theory]
    [InlineData(2048, 2048, true)]
    [InlineData(4096, 2048, true)]
    [InlineData(1024, 2048, false)]
    public void ServerCreationPlanValidatesMemoryInvariants(int maxMb, int minMb, bool shouldSucceed)
    {
        Action act = () => _ = new ServerCreationPlan(
            "tx-test",
            ServerName.Parse("MemTest"),
            MinecraftVersion.Parse("1.20.1"),
            LoaderKind.Vanilla,
            "",
            memoryMaxMb: maxMb,
            memoryMinMb: minMb,
            jvmArgs: [],
            properties: [],
            finalPath: "",
            stagingPath: ""
        );

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
    public void ServerImportBatchResultAggregatesCounters()
    {
        var batch = new ServerImportBatchResult([
            ServerImportResult.Success("server1", new ServerConfig(ServerName.Parse("server1"), MinecraftVersion.Parse("1.20.1"), LoaderKind.Vanilla, "", 2048)),
            ServerImportResult.Skipped("server2", "已存在相同伺服器"),
            ServerImportResult.Failed("server3", "檔案損毀", diagnosticId: "diag-001"),
        ]);

        Assert.Equal(3, batch.Items.Count);
        Assert.Equal(1, batch.CompletedCount);
        Assert.Equal(1, batch.SkippedCount);
        Assert.Equal(1, batch.FailedCount);
    }

    [Fact]
    public void OnlineModCompatibilityReportDeterminesCompatibility()
    {
        var compatibleReport = new OnlineModCompatibilityReport(
            hardErrors: [],
            incompatibleInstalled: [],
            missingRequiredDependencies: [],
            warnings: ["此為 Beta 測試版"]
        );
        Assert.True(compatibleReport.IsCompatible);
        Assert.False(compatibleReport.HasHardErrors);

        var incompatibleReport = new OnlineModCompatibilityReport(
            hardErrors: ["遊戲版本不相容"],
            missingRequiredDependencies: ["fabric-api"]
        );
        Assert.False(incompatibleReport.IsCompatible);
        Assert.True(incompatibleReport.HasHardErrors);
    }

    [Fact]
    public void LocalModUpdateCandidateReflectsUpdateAvailability()
    {
        var localMod = new LocalModInfo("sodium", "Sodium", "sodium.jar", "0.5.8", "1.20.4", "fabric");
        var candidateWithUpdate = new LocalModUpdateCandidate(localMod, new OnlineModVersion("v2", "0.5.9", "Sodium 0.5.9"));
        var candidateWithoutUpdate = new LocalModUpdateCandidate(localMod, null);

        Assert.True(candidateWithUpdate.HasUpdate);
        Assert.False(candidateWithoutUpdate.HasUpdate);
    }
}

