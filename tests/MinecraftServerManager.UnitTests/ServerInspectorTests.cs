using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerInspectorTests : IDisposable
{
    private readonly string _testRoot;

    public ServerInspectorTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-inspector-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testRoot);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testRoot))
            {
                Directory.Delete(_testRoot, recursive: true);
            }
        }
        catch
        {
        }
    }

    [Fact]
    public async Task InspectsVanillaServerSuccessfully()
    {
        string serverDir = Path.Combine(_testRoot, "vanilla-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(serverDir, "server.properties"), "server-port=25565\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir);

        Assert.True(inspection.IsCandidate);
        Assert.True(inspection.Launchable);
        Assert.Equal(EulaState.Accepted, inspection.EulaState);
        Assert.Equal("vanilla", inspection.LoaderType);
        Assert.Equal("server.jar", inspection.LaunchTarget.Value);
        Assert.Equal(LaunchTargetKind.Jar, inspection.LaunchTarget.Kind);
    }

    [Fact]
    public async Task PrefersRunBatAsPrimaryLaunchTarget()
    {
        string serverDir = Path.Combine(_testRoot, "forge-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "run.bat"), "@echo off\njava -jar server.jar\n");
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir);

        Assert.Equal("run.bat", inspection.LaunchTarget.Value);
        Assert.Equal(LaunchTargetKind.Script, inspection.LaunchTarget.Kind);
        Assert.Contains("run.bat", inspection.LaunchTarget.Reason);
        Assert.Contains("server.jar", inspection.LaunchTarget.Candidates);
    }

    [Fact]
    public async Task DetectsFabricLoaderAndMemoryArgs()
    {
        string serverDir = Path.Combine(_testRoot, "fabric-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "fabric-server-launch.jar"), "dummy fabric");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(serverDir, "user_jvm_args.txt"), "-Xms2G\n-Xmx6G\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir);

        Assert.Equal("fabric", inspection.LoaderType);
        Assert.Equal("fabric-server-launch.jar", inspection.LaunchTarget.Value);
        Assert.Equal(6144, inspection.MemoryMaxMb);
        Assert.Equal(2048, inspection.MemoryMinMb);
    }

    [Fact]
    public async Task DetectsDeclinedEula()
    {
        string serverDir = Path.Combine(_testRoot, "declined-server");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy");
        File.WriteAllText(Path.Combine(serverDir, "eula.txt"), "eula=false\n");

        var inspector = new ServerInspector();
        var inspection = await inspector.InspectAsync(serverDir);

        Assert.Equal(EulaState.Rejected, inspection.EulaState);
        Assert.False(inspection.Launchable);
    }
}
