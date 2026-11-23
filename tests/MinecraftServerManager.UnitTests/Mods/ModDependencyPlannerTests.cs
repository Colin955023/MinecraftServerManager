using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Mods;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class ModDependencyPlannerTests
{
    [Fact]
    public void EvaluateCompatibility_AllMatch_IsCompatible()
    {
        var planner = new ModDependencyPlanner(new StubModrinthClient());
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Mod 1.0",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            datePublished: "",
            files: [new ModFile("mod.jar", "https://example.com/mod.jar", true, 100, new Dictionary<string, string>())],
            dependencies: [new OnlineModDependency("fabric-api", ModDependencyType.Required)]);

        var installedMods = new List<LocalModInfo>
        {
            new("fabric-api", "Fabric API", "fabric-api.jar", "0.92.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", LoaderKind.Fabric, installedMods);

        Assert.Empty(report.HardErrors);
        Assert.Empty(report.MissingRequiredDependencies);
    }

    [Theory]
    [InlineData("forge", LoaderKind.Fabric, "1.20.1", "", false, "載入器")]
    [InlineData("fabric", LoaderKind.Fabric, "1.20.1", "unsupported", false, "僅支援用戶端")]
    [InlineData("fabric", LoaderKind.Quilt, "1.20.1", "", true, null)]
    [InlineData("forge", LoaderKind.NeoForge, "1.20.1", "", true, null)]
    [InlineData("forge", LoaderKind.Paper, "1.20.1", "", false, "不支援")]
    public void EvaluateCompatibility_LoaderAndEnvironmentMatrix_MatchesExpectation(
        string modLoader,
        LoaderKind serverLoader,
        string mcVersion,
        string serverSide,
        bool expectCompatible,
        string? expectedErrorSubstring)
    {
        var planner = new ModDependencyPlanner(new StubModrinthClient());
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Test Mod",
            gameVersions: [mcVersion],
            loaders: [modLoader],
            versionType: "release");

        var report = planner.EvaluateCompatibility(targetVersion, mcVersion, serverLoader, [], serverSide: serverSide);

        if (expectCompatible)
        {
            Assert.Empty(report.HardErrors);
        }
        else
        {
            Assert.NotEmpty(report.HardErrors);
            if (expectedErrorSubstring is not null)
            {
                Assert.Contains(report.HardErrors, e => e.Contains(expectedErrorSubstring, StringComparison.Ordinal));
            }
        }
    }

    [Fact]
    public void EvaluateCompatibility_MissingRequiredDependency_ReportsMissing()
    {
        var planner = new ModDependencyPlanner(new StubModrinthClient());
        var targetVersion = new OnlineModVersion(
            versionId: "v1",
            versionNumber: "1.0",
            displayName: "Mod 1.0",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            dependencies: [new OnlineModDependency("cloth-config", ModDependencyType.Required)]);

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", LoaderKind.Fabric, []);

        Assert.NotEmpty(report.HardErrors);
        Assert.Contains("cloth-config", report.MissingRequiredDependencies);
    }

    [Fact]
    public void EvaluateCompatibility_IncompatibleModInstalled_ReportsError()
    {
        var planner = new ModDependencyPlanner(new StubModrinthClient());
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

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", LoaderKind.Fabric, installedMods);

        Assert.NotEmpty(report.HardErrors);
        Assert.Contains("optifine", report.IncompatibleInstalled);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_CyclicTree_ResolvesOnce()
    {
        var stubClient = new StubModrinthClient();
        var planner = new ModDependencyPlanner(stubClient);

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
            files: [new ModFile("mod-b.jar", "https://example.com/mod-b.jar", true, 100, new Dictionary<string, string>())]);

        var versionC = new OnlineModVersion(
            "ver-c", "1.0", "Mod C",
            dependencies: [
                new OnlineModDependency("mod-a", ModDependencyType.Required) // 循環指向起點
            ],
            files: [new ModFile("mod-c.jar", "https://example.com/mod-c.jar", true, 100, new Dictionary<string, string>())]);

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
            initialDeps,
            serverMinecraftVersion: "1.20.1",
            serverLoader: LoaderKind.Fabric,
            installedMods: installedMods,
            cancellationToken: TestContext.Current.CancellationToken);

        // 應成功解析出 mod-b 與 mod-c，且略過已安裝相容的 mod-installed 與循環的 mod-a
        Assert.Equal(2, result.Count);
        Assert.Contains(result, static v => v.TargetVersion.VersionId == "ver-b" && v.Action == ModInstallAction.Install);
        Assert.Contains(result, static v => v.TargetVersion.VersionId == "ver-c" && v.Action == ModInstallAction.Install);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_WhenInstalledModOutdated_PlansUpdate()
    {
        var stubClient = new StubModrinthClient();
        var planner = new ModDependencyPlanner(stubClient);

        var versionDepNew = new OnlineModVersion(
            "ver-dep-new", "2.0.0", "Dep Mod",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            files: [new ModFile("dep-2.0.0.jar", "https://example.com/dep-2.0.0.jar", true, 100, new Dictionary<string, string>())]);

        stubClient.Versions["dep-mod"] = [versionDepNew];

        var installedMods = new List<LocalModInfo>
        {
            new("dep-mod", "Dep Mod", "dep-1.0.0.jar", "1.0.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var result = await planner.ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("dep-mod", ModDependencyType.Required)],
            serverMinecraftVersion: "1.20.1",
            serverLoader: LoaderKind.Fabric,
            installedMods: installedMods,
            cancellationToken: TestContext.Current.CancellationToken);

        // 應標記為 Update，且關聯既有本地模組
        var plan = Assert.Single(result);
        Assert.Equal(ModInstallAction.Update, plan.Action);
        Assert.Equal("ver-dep-new", plan.TargetVersion.VersionId);
        Assert.NotNull(plan.ExistingLocalMod);
        Assert.Equal("1.0.0", plan.ExistingLocalMod.Version);
    }

    [Fact]
    public void EvaluateCompatibility_WellKnownModAlias_RecognizesInstalled()
    {
        var planner = new ModDependencyPlanner(new StubModrinthClient());
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

        var report = planner.EvaluateCompatibility(targetVersion, "1.20.1", LoaderKind.Fabric, installedMods);

        Assert.Empty(report.HardErrors);
        Assert.Empty(report.MissingRequiredDependencies);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_ReleaseAndBeta_PrefersRelease()
    {
        var stubClient = new StubModrinthClient();
        var planner = new ModDependencyPlanner(stubClient);

        var betaVersion = new OnlineModVersion(
            "ver-beta", "2.0-beta", "Mod Beta",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "beta",
            files: [new ModFile("beta.jar", "https://example.com/beta.jar", true, 100, new Dictionary<string, string>())]);

        var releaseVersion = new OnlineModVersion(
            "ver-release", "1.9.0", "Mod Release",
            gameVersions: ["1.20.1"],
            loaders: ["fabric"],
            versionType: "release",
            files: [new ModFile("release.jar", "https://example.com/release.jar", true, 100, new Dictionary<string, string>())]);

        stubClient.Versions["target-dep"] = [betaVersion, releaseVersion];

        var result = await planner.ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("target-dep", ModDependencyType.Required)],
            serverMinecraftVersion: "1.20.1",
            serverLoader: LoaderKind.Fabric,
            installedMods: [],
            cancellationToken: TestContext.Current.CancellationToken);

        var plan = Assert.Single(result);
        Assert.Equal("ver-release", plan.TargetVersion.VersionId);
    }

    private static ModFile JarFile(string name, string sha1 = "") =>
        new(name, $"https://example.com/{name}", true, 100, sha1.Length == 0 ? new Dictionary<string, string>() : new Dictionary<string, string> { ["sha1"] = sha1 });

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_InstalledModWithWhitespaceInName_MatchesAndUpgradesCorrectly()
    {
        var stubClient = new StubModrinthClient();
        stubClient.Versions["fabric-api"] =
        [
            new OnlineModVersion("ver-new", "0.95.0", "Fabric API", gameVersions: ["1.20.1"], loaders: ["fabric"], files: [JarFile("fabric-api-0.95.0.jar")])
        ];

        var installed = new List<LocalModInfo>
        {
            new("fabric-api", "Fabric API", "fabric-api-0.90.0.jar", "0.90.0", "1.20.1", "fabric", status: ModStatus.Enabled)
        };

        var result = await new ModDependencyPlanner(stubClient).ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("fabric-api", ModDependencyType.Required)],
            "1.20.1",
            LoaderKind.Fabric,
            installed,
            cancellationToken: TestContext.Current.CancellationToken);

        var plan = Assert.Single(result);
        Assert.Equal(ModInstallAction.Update, plan.Action);
        Assert.Equal("ver-new", plan.TargetVersion.VersionId);
        Assert.NotNull(plan.ExistingLocalMod);
        Assert.Equal("Fabric API", plan.ExistingLocalMod.Name);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_NewerInstalled_DoesNotDowngrade()
    {
        var stubClient = new StubModrinthClient();
        stubClient.Versions["dep-mod"] = [new OnlineModVersion("ver-old", "1.0.0", "Dep", gameVersions: ["1.20.1"], loaders: ["fabric"], files: [JarFile("dep-1.0.0.jar")])];
        var installed = new List<LocalModInfo> { new("dep-mod", "Dep", "dep-2.0.0.jar", "2.0.0", "1.20.1", "fabric", status: ModStatus.Enabled) };

        var result = await new ModDependencyPlanner(stubClient).ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("dep-mod", ModDependencyType.Required)], "1.20.1", LoaderKind.Fabric, installed,
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.Empty(result);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_SameVersionInstalled_ExpandsChildren()
    {
        var stubClient = new StubModrinthClient();
        stubClient.Versions["lib-a"] = [new OnlineModVersion("ver-a", "1.0", "Lib A", gameVersions: ["1.20.1"], loaders: ["fabric"],
            dependencies: [new OnlineModDependency("lib-b", ModDependencyType.Required)], files: [JarFile("lib-a.jar", "abc")])];
        stubClient.Versions["lib-b"] = [new OnlineModVersion("ver-b", "1.0", "Lib B", gameVersions: ["1.20.1"], loaders: ["fabric"], files: [JarFile("lib-b.jar")])];
        var installed = new List<LocalModInfo> { new("lib-a", "Lib A", "lib-a.jar", "1.0", "1.20.1", "fabric", status: ModStatus.Enabled, currentHash: "abc", hashAlgorithm: "sha1") };

        var result = await new ModDependencyPlanner(stubClient).ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("lib-a", ModDependencyType.Required)], "1.20.1", LoaderKind.Fabric, installed,
            cancellationToken: TestContext.Current.CancellationToken);

        var plan = Assert.Single(result);
        Assert.Equal("ver-b", plan.TargetVersion.VersionId);
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_DisabledModsAndRoot_IgnoresThem()
    {
        var stubClient = new StubModrinthClient();
        stubClient.Versions["dep-mod"] = [new OnlineModVersion("ver-dep", "1.0", "Dep", gameVersions: ["1.20.1"], loaders: ["fabric"],
            dependencies: [new OnlineModDependency("root-mod", ModDependencyType.Required)], files: [JarFile("dep.jar")])];
        stubClient.Versions["root-mod"] = [new OnlineModVersion("ver-root", "1.0", "Root", gameVersions: ["1.20.1"], loaders: ["fabric"], files: [JarFile("root.jar")])];
        var installed = new List<LocalModInfo> { new("dep-mod", "Dep", "dep.jar.disabled", "1.0", "1.20.1", "fabric", status: ModStatus.Disabled) };

        var result = await new ModDependencyPlanner(stubClient).ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("dep-mod", ModDependencyType.Required)], "1.20.1", LoaderKind.Fabric, installed, rootProjectId: "root-mod",
            cancellationToken: TestContext.Current.CancellationToken);

        var plan = Assert.Single(result);
        Assert.Equal(ModInstallAction.Install, plan.Action);
        Assert.Equal("ver-dep", plan.TargetVersion.VersionId);
    }

    [Theory]
    [InlineData("1.20.1", true)]
    [InlineData("1.20.10", false)]
    public async Task ResolveDependenciesRecursivelyAsync_NeoForge_FallsBackToForgeOnlyOn1201(string mcVersion, bool expectResolved)
    {
        var stubClient = new StubModrinthClient();
        stubClient.LoaderVersions["forge-lib|forge"] = [new OnlineModVersion("ver-forge", "1.0", "Forge Lib", gameVersions: [mcVersion], loaders: ["forge"], files: [JarFile("forge-lib.jar")])];

        var result = await new ModDependencyPlanner(stubClient).ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("forge-lib", ModDependencyType.Required)], mcVersion, LoaderKind.NeoForge, [],
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(expectResolved, result.Count == 1);
        Assert.Equal(expectResolved, stubClient.RequestedLoaders.Contains(LoaderKind.Forge));
    }

    [Fact]
    public async Task ResolveDependenciesRecursivelyAsync_NoMatchingVersion_ReturnsNothing()
    {
        var stubClient = new StubModrinthClient();
        stubClient.Versions["dep-mod"] = [new OnlineModVersion("ver-forge", "1.0", "Dep", gameVersions: ["1.20.1"], loaders: ["forge"], files: [JarFile("dep.jar")])];

        var result = await new ModDependencyPlanner(stubClient).ResolveDependenciesRecursivelyAsync(
            [new OnlineModDependency("dep-mod", ModDependencyType.Required)], "1.20.1", LoaderKind.Fabric, [],
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.Empty(result);
    }
}
