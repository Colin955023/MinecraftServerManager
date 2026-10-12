using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerPropertiesMigrationTests
{
    [Fact]
    public void PlanMigrationShouldRenameTexturePackToResourcePack()
    {
        var input = new Dictionary<string, string>
        {
            ["texture-pack"] = "https://example.com/pack.zip"
        };

        var plan = ServerPropertiesMigrationService.PlanMigration(input);

        Assert.True(plan.NeedsMigration);
        Assert.False(plan.MigratedProperties.ContainsKey("texture-pack"));
        Assert.Equal("https://example.com/pack.zip", plan.MigratedProperties["resource-pack"]);
        Assert.Single(plan.Changes);
    }

    [Fact]
    public void PlanMigrationShouldConvertNumericGamemodeAndDifficulty()
    {
        var input = new Dictionary<string, string>
        {
            ["gamemode"] = "1",
            ["difficulty"] = "2"
        };

        var plan = ServerPropertiesMigrationService.PlanMigration(input);

        Assert.True(plan.NeedsMigration);
        Assert.Equal("creative", plan.MigratedProperties["gamemode"]);
        Assert.Equal("normal", plan.MigratedProperties["difficulty"]);
        Assert.Equal(2, plan.Changes.Count);
    }

    [Fact]
    public void PlanMigrationShouldConvertLevelTypeOnVersion119AndAbove()
    {
        var input = new Dictionary<string, string>
        {
            ["level-type"] = "flat"
        };

        var planBelow119 = ServerPropertiesMigrationService.PlanMigration(input, "1.18.2");
        Assert.False(planBelow119.NeedsMigration);
        Assert.Equal("flat", planBelow119.MigratedProperties["level-type"]);

        var plan119 = ServerPropertiesMigrationService.PlanMigration(input, "1.19.4");
        Assert.True(plan119.NeedsMigration);
        Assert.Equal("minecraft:flat", plan119.MigratedProperties["level-type"]);
    }

    [Fact]
    public void PlanMigrationShouldRemoveDeprecatedProperties()
    {
        var input = new Dictionary<string, string>
        {
            ["max-build-height"] = "256",
            ["snooper-enabled"] = "true",
            ["announce-player-achievements"] = "true",
            ["server-port"] = "25565"
        };

        var plan = ServerPropertiesMigrationService.PlanMigration(input);

        Assert.True(plan.NeedsMigration);
        Assert.False(plan.MigratedProperties.ContainsKey("max-build-height"));
        Assert.False(plan.MigratedProperties.ContainsKey("snooper-enabled"));
        Assert.False(plan.MigratedProperties.ContainsKey("announce-player-achievements"));
        Assert.Equal("25565", plan.MigratedProperties["server-port"]);
        Assert.Equal(3, plan.Changes.Count);
    }

    [Fact]
    public void PlanMigrationWithCleanPropertiesShouldReportNoMigration()
    {
        var input = new Dictionary<string, string>
        {
            ["server-port"] = "25565",
            ["difficulty"] = "hard",
            ["gamemode"] = "survival"
        };

        var plan = ServerPropertiesMigrationService.PlanMigration(input, "1.20.4");

        Assert.False(plan.NeedsMigration);
        Assert.Empty(plan.Changes);
        Assert.Equal("設定檔符合最新規範，無需遷移", plan.Summary());
    }
}
