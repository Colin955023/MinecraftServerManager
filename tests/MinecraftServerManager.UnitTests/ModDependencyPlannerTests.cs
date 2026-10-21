using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組相容性與相依性規劃測試
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
        Assert.Contains(report.HardErrors, static e => e.Contains("載入器", StringComparison.Ordinal));
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

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_ResolvesTreeAndAvoidsCycles()
    {
        var planner = new ModDependencyPlanner();
        var stubClient = new StubModrinthClient();

        // 模擬專案相依結構：
        // mod-a 相依於 mod-b (Required)
        // mod-b 相依於 mod-c (Required) 與 已安裝的 mod-installed (Required)
        // mod-c 相依於 mod-a (循環相依，應被防禦略過)
        var versionB = new OnlineModVersion(
            "ver-b", "1.0", "Mod B",
            dependencies: [
                new OnlineModDependency("mod-c", ModDependencyType.Required),
                new OnlineModDependency("mod-installed", ModDependencyType.Required)
            ],
            files: [new ModFile("https://example.com/mod-b.jar", "mod-b.jar", true, 100, new Dictionary<string, string>())]);

        var versionC = new OnlineModVersion(
            "ver-c", "1.0", "Mod C",
            dependencies: [
                new OnlineModDependency("mod-a", ModDependencyType.Required) // 循環指向起點
            ],
            files: [new ModFile("https://example.com/mod-c.jar", "mod-c.jar", true, 100, new Dictionary<string, string>())]);

        stubClient.Versions["mod-b"] = [versionB];
        stubClient.Versions["mod-c"] = [versionC];

        var installedMods = new List<LocalModInfo>
        {
            new("mod-installed", "Mod Installed", "mod-installed.jar", "1.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var initialDeps = new List<OnlineModDependency>
        {
            new("mod-b", ModDependencyType.Required)
        };

        var result = await planner.ResolveDependenciesRecursivelyAsync(
            stubClient,
            initialDeps,
            serverMinecraftVersion: "1.20.1",
            serverLoader: "fabric",
            installedMods: installedMods);

        // 應成功解析出 mod-b 與 mod-c，且略過已安裝相容的 mod-installed 與循環的 mod-a
        Assert.Equal(2, result.Count);
        Assert.Contains(result, static v => v.TargetVersion.VersionId == "ver-b" && v.Action == ModInstallAction.Install);
        Assert.Contains(result, static v => v.TargetVersion.VersionId == "ver-c" && v.Action == ModInstallAction.Install);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_WhenInstalledModOutdated_PlansUpdate()
    {
        var planner = new ModDependencyPlanner();
        var stubClient = new StubModrinthClient();

        var versionDepNew = new OnlineModVersion(
            "ver-dep-new", "2.0.0", "Dep Mod",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            files: [new ModFile("https://example.com/dep-2.0.0.jar", "dep-2.0.0.jar", true, 100, new Dictionary<string, string>())]);

        stubClient.Versions["dep-mod"] = [versionDepNew];

        var installedMods = new List<LocalModInfo>
        {
            new("dep-mod", "Dep Mod", "dep-1.0.0.jar", "1.0.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var result = await planner.ResolveDependenciesRecursivelyAsync(
            stubClient,
            [new OnlineModDependency("dep-mod", ModDependencyType.Required)],
            serverMinecraftVersion: "1.20.1",
            serverLoader: "fabric",
            installedMods: installedMods);

        // 應標記為 Update，且關聯既有本地模組
        var plan = Assert.Single(result);
        Assert.Equal(ModInstallAction.Update, plan.Action);
        Assert.Equal("ver-dep-new", plan.TargetVersion.VersionId);
        Assert.NotNull(plan.ExistingLocalMod);
        Assert.Equal("1.0.0", plan.ExistingLocalMod.Version);
    }

    [Fact]
    public void EvaluateCompatibilityWhenServerSideUnsupportedShouldReportHardError()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Client Only Mod",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release");

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "fabric", [], serverSide: "unsupported");

        Assert.False(report.Compatible);
        Assert.Contains(report.HardErrors, static e => e.Contains("僅支援用戶端", StringComparison.Ordinal));
    }

    [Fact]
    public void EvaluateCompatibilityQuiltServerWithFabricModShouldBeCompatible()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Fabric Mod",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release");

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "quilt", []);

        Assert.True(report.Compatible);
        Assert.Empty(report.HardErrors);
    }

    [Fact]
    public void EvaluateCompatibilityNeoForge1201ServerWithForgeModShouldBeCompatible()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Forge Mod",
            gameVersions: ["1.20.1"],
            loaders: ["forge"],
            versionType: "release");

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "neoforge", []);

        Assert.True(report.Compatible);
        Assert.Empty(report.HardErrors);
    }

    [Fact]
    public void EvaluateCompatibilityPluginServerWithForgeModShouldReportHardError()
    {
        var planner = new ModDependencyPlanner();
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Forge Mod",
            gameVersions: ["1.20.1"],
            loaders: ["forge"],
            versionType: "release");

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "paper", []);

        Assert.False(report.Compatible);
        Assert.Contains(report.HardErrors, static e => e.Contains("不支援", StringComparison.Ordinal));
    }

    [Fact]
    public void EvaluateCompatibilityWithWellKnownModAliasShouldRecognizeInstalled()
    {
        var planner = new ModDependencyPlanner();
        // 相依項為 Modrinth Project ID: P7dR8mAc (Fabric API)
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Some Mod",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            dependencies: [new OnlineModDependency("P7dR8mAc", ModDependencyType.Required)]);

        // 本地安裝的模組 ID 為 fabric-api
        var installedMods = new List<LocalModInfo>
        {
            new("fabric-api", "Fabric API", "fabric-api.jar", "0.92.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", "fabric", installedMods);

        Assert.True(report.Compatible);
        Assert.Empty(report.MissingRequired);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsyncPrefersReleaseVersionsOverBeta()
    {
        var planner = new ModDependencyPlanner();
        var stubClient = new StubModrinthClient();

        var betaVersion = new OnlineModVersion(
            "ver-beta", "2.0-beta", "Mod Beta",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "beta",
            files: [new ModFile("https://example.com/beta.jar", "beta.jar", true, 100, new Dictionary<string, string>())]);

        var releaseVersion = new OnlineModVersion(
            "ver-release", "1.9.0", "Mod Release",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            files: [new ModFile("https://example.com/release.jar", "release.jar", true, 100, new Dictionary<string, string>())]);

        stubClient.Versions["target-dep"] = [betaVersion, releaseVersion];

        var result = await planner.ResolveDependenciesRecursivelyAsync(
            stubClient,
            [new OnlineModDependency("target-dep", ModDependencyType.Required)],
            serverMinecraftVersion: "1.20.1",
            serverLoader: "fabric",
            installedMods: []);

        var plan = Assert.Single(result);
        Assert.Equal("ver-release", plan.TargetVersion.VersionId);
    }

    private sealed class StubModrinthClient : Core.Ports.IModrinthClient
    {
        public Dictionary<string, IReadOnlyList<OnlineModVersion>> Versions { get; } = new(StringComparer.OrdinalIgnoreCase);

        public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(string projectIdOrSlug, string? loader = null, string? minecraftVersion = null, CancellationToken cancellationToken = default)
        {
            if (Versions.TryGetValue(projectIdOrSlug, out var list))
            {
                return Task.FromResult(list);
            }
            return Task.FromResult<IReadOnlyList<OnlineModVersion>>([]);
        }

        public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(string query, string? loader = null, string? minecraftVersion = null, int limit = 20, int offset = 0, string index = "relevance", CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<OnlineModInfo>>([]);

        public Task<ModrinthVersionLookupResult?> LookupVersionByHashAsync(string hash, string algorithm = "sha512", CancellationToken cancellationToken = default) =>
            Task.FromResult<ModrinthVersionLookupResult?>(null);

        public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(IReadOnlyList<string> hashes, string algorithm = "sha512", CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyDictionary<string, ModrinthVersionLookupResult>>(new Dictionary<string, ModrinthVersionLookupResult>());
    }
}
