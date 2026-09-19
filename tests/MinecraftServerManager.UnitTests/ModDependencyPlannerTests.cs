using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組相容性與依賴規劃測試
/// </summary>
public sealed class ModDependencyPlannerTests
{
    [Fact]
    public void EvaluateCompatibilityWhenAllMatchShouldBeCompatible()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Mod 1.0",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            datePublished: "",
            changelog: "",
            files: [new ModFile("https://example.com/mod.jar", "mod.jar", true, 100, new Dictionary<string, string>())],
            dependencies: [new OnlineModDependency("fabric-api", ModDependencyType.Required)]);

        var installedMods = new List<LocalModInfo>
        {
            new("fabric-api", "Fabric API", "fabric-api.jar", "0.92.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "fabric", installedMods);

        Assert.True(report.Compatible);
        Assert.Empty(report.HardErrors);
        Assert.Empty(report.MissingRequired);
    }

    [Fact]
    public void EvaluateCompatibilityWhenLoaderMismatchesShouldReportError()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Mod 1.0",
            gameVersions: ["1.20.1"],
            loaders: ["forge"],
            versionType: "release");

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "fabric", []);

        Assert.False(report.Compatible);
        Assert.Contains(report.HardErrors, e => e.Contains("載入器", StringComparison.Ordinal));
    }

    [Fact]
    public void EvaluateCompatibilityWhenMissingRequiredDependencyShouldReportMissing()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Mod 1.0",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            dependencies: [new OnlineModDependency("cloth-config", ModDependencyType.Required)]);

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "fabric", []);

        Assert.False(report.Compatible);
        Assert.Contains("cloth-config", report.MissingRequired);
    }

    [Fact]
    public void EvaluateCompatibilityWhenIncompatibleModInstalledShouldReportError()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Mod 1.0",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            dependencies: [new OnlineModDependency("optifine", ModDependencyType.Incompatible)]);

        var installedMods = new List<LocalModInfo>
        {
            new("optifine", "OptiFine", "optifine.jar", "1.20.1", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "fabric", installedMods);

        Assert.False(report.Compatible);
        Assert.Contains("optifine", report.Incompatible);
    }
}
