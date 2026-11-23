using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerPropertiesMigrationTests
{
    [Fact]
    public void PlanMigration_TexturePack_RenamesToResourcePack()
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
    public void PlanMigration_NumericModes_ConvertsToNames()
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
    public void PlanMigration_LevelTypeOn119Plus_Converts()
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
    public void PlanMigration_DeprecatedProperties_Removes()
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
    public void PlanMigration_CleanProperties_ReportsNoMigration()
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
    }

    [Fact]
    public void PlanMigration_DuplicateHellworld_Records()
    {
        var plan = ServerPropertiesMigrationService.PlanMigration(new Dictionary<string, string>
        {
            ["hellworld"] = "false",
            ["allow-nether"] = "true",
        }, "1.20.4");

        Assert.True(plan.NeedsMigration);
        Assert.False(plan.MigratedProperties.ContainsKey("hellworld"));
        Assert.Equal("true", plan.MigratedProperties["allow-nether"]);
        Assert.Contains(plan.Changes, static c => c.Contains("hellworld", StringComparison.Ordinal));
    }

    [Fact]
    public void PlanMigration_LegacyVersion_KeepsNumericModes()
    {
        var plan = ServerPropertiesMigrationService.PlanMigration(new Dictionary<string, string>
        {
            ["gamemode"] = "1",
            ["difficulty"] = "2",
        }, "1.12.2");

        Assert.False(plan.NeedsMigration);
        Assert.Equal("1", plan.MigratedProperties["gamemode"]);
        Assert.Equal("2", plan.MigratedProperties["difficulty"]);
    }

    [Fact]
    public void PlanMigration_Legacy112Version_KeepsMaxBuildHeightAndSnooperEnabled()
    {
        var plan = ServerPropertiesMigrationService.PlanMigration(new Dictionary<string, string>
        {
            ["max-build-height"] = "256",
            ["snooper-enabled"] = "true",
            ["announce-player-achievements"] = "true",
        }, "1.12.2");

        Assert.True(plan.NeedsMigration);
        Assert.Equal("256", plan.MigratedProperties["max-build-height"]);
        Assert.Equal("true", plan.MigratedProperties["snooper-enabled"]);
        Assert.False(plan.MigratedProperties.ContainsKey("announce-player-achievements"));
    }
}
