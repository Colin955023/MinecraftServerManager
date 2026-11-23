using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerInspectorTests : IDisposable
{
    private readonly TempDirectory _testRootTemp = new("msm-inspector-tests-");
    private readonly string _testRoot;

    public ServerInspectorTests()
    {
        _testRoot = _testRootTemp.FullName;
    }

    public void Dispose() => _testRootTemp.Dispose();

    [Fact]
    public async Task Inspect_VanillaServer_ReturnsDetails()
    {
        string serverDir = Path.Combine(_testRoot, "vanilla-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(serverDir, "server.properties"), "server-port=25565\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.True(inspection.IsCandidate);
        Assert.Equal(LoaderKind.Vanilla, inspection.LoaderType);
        Assert.Equal("server.jar", inspection.LaunchTarget.Value);
        Assert.Equal(LaunchTargetKind.Jar, inspection.LaunchTarget.Kind);
    }

    [Fact]
    public async Task Inspect_RunBatPresent_PrefersRunBat()
    {
        string serverDir = Path.Combine(_testRoot, "forge-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "run.bat"), "@echo off\njava -jar server.jar\n");
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.Equal("run.bat", inspection.LaunchTarget.Value);
        Assert.Equal(LaunchTargetKind.Script, inspection.LaunchTarget.Kind);
        Assert.Contains("run.bat", inspection.LaunchTarget.Reason);
        Assert.Contains("server.jar", inspection.LaunchTarget.Candidates);
    }

    [Fact]
    public async Task Inspect_FabricServer_DetectsLoaderAndMemory()
    {
        string serverDir = Path.Combine(_testRoot, "fabric-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "fabric-server-launch.jar"), "dummy fabric");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(serverDir, "user_jvm_args.txt"), "-Xms2G\n-Xmx6G\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.Equal(LoaderKind.Fabric, inspection.LoaderType);
        Assert.Equal("fabric-server-launch.jar", inspection.LaunchTarget.Value);
        Assert.Equal(6144, inspection.MemoryMaxMb);
        Assert.Equal(2048, inspection.MemoryMinMb);
    }

    [Fact]
    public async Task Inspect_PaperServer_DetectsLoader()
    {
        string serverDir = Path.Combine(_testRoot, "paper-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "paper-1.20.4-497.jar"), "dummy paper jar");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(serverDir, "paper-global.yml"), "# paper config\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.True(inspection.IsCandidate);
        Assert.Equal(LoaderKind.Paper, inspection.LoaderType);
        Assert.Equal("paper-1.20.4-497.jar", inspection.LaunchTarget.Value);
        Assert.Equal(LaunchTargetKind.Jar, inspection.LaunchTarget.Kind);
    }

    [Fact]
    public async Task Inspect_OversizedMetadata_IgnoresIt()
    {
        string serverDir = Path.Combine(_testRoot, "oversized-metadata-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(serverDir, "server.properties"), "server-port=25565\n");

        // 建立 3MB 的超大 version.json
        string largeVersion = Path.Combine(serverDir, "version.json");
        using (var fs = new FileStream(largeVersion, FileMode.Create, FileAccess.Write))
        {
            fs.SetLength(3L * 1024 * 1024);
        }

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.True(inspection.IsCandidate);
        Assert.Null(inspection.MinecraftVersion); // 超大 version.json 被安全忽略，不致當機
    }

    [Fact]
    public async Task Inspect_EmptyDirectory_ReturnsUnknownAndNotReady()
    {
        string serverDir = Path.Combine(_testRoot, "empty-server");
        Directory.CreateDirectory(serverDir);

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);

        Assert.False(inspection.IsCandidate);
        Assert.Equal(LoaderKind.Unknown, inspection.LoaderType);
        Assert.Null(inspection.LoaderVersion);
        Assert.Null(inspection.MinecraftVersion);
    }

    [Theory]
    [InlineData("Manifest-Version: 1.0\nImplementation-Version: 1.20.4\n", "1.20.4")]
    [InlineData("Manifest-Version: 1.0\nSpecification-Version: 1.19.2\n", "1.19.2")]
    [InlineData("Manifest-Version: 1.0\nCreated-By: 17.0.1\n", null)]
    public void ExtractMinecraftVersionFromManifest_MixedKeys_ReadsOnlyVersionKeys(string manifest, string? expected) =>
        Assert.Equal(expected, ServerInspector.ExtractMinecraftVersionFromManifest(manifest));

    [Fact]
    public async Task Inspect_MultipleLoaderLibraries_PicksNewest()
    {
        string serverDir = Path.Combine(_testRoot, "fabric-multi");
        string libDir = Path.Combine(serverDir, "libraries", "net", "fabricmc", "fabric-loader");
        Directory.CreateDirectory(Path.Combine(libDir, "0.9.3"));
        Directory.CreateDirectory(Path.Combine(libDir, "0.16.10"));
        Directory.CreateDirectory(Path.Combine(libDir, "0.15.11"));
        File.WriteAllText(Path.Combine(serverDir, "fabric-server-launch.jar"), "dummy");
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy");

        var inspection = await new ServerInspector().InspectAsync(serverDir, cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal("0.16.10", inspection.LoaderVersion);
    }
}
