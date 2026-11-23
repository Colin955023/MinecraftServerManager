using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>建立不連網、不安裝載入器的測試用 ServerManager</summary>
internal static class TestServerManagers
{
    public static ServerManager Create(string serversRoot, IServerInspector? inspector = null) =>
        new(
            serversRoot,
            inspector ?? new ServerInspector(),
            new StubLoaderInstaller(),
            new FixedJavaRuntimeDetector(),
            new FixedJavaRequirementService());

    public static async Task<ServerConfig> CreateVanillaServerAsync(
        this ServerManager manager,
        string name = "test-server",
        string minecraftVersion = "1.21.4",
        int memoryMb = 2048,
        CancellationToken cancellationToken = default)
    {
        var result = await manager.CreateServerAsync(
            new ServerCreationPlan(
                TestServerConfigs.Create(name, minecraftVersion, LoaderKind.Vanilla, memoryMaxMb: memoryMb)),
            cancellationToken: cancellationToken);
        return result.Config!;
    }

    private sealed class StubLoaderInstaller : ILoaderInstallerService
    {
        public Task<string> InstallLoaderAsync(
            LoaderKind loader,
            string minecraftVersion,
            string loaderVersion,
            string serverDirectory,
            string javaExecutablePath,
            IProgress<LoaderInstallProgress>? progress = null,
            CancellationToken cancellationToken = default)
        {
            File.WriteAllText(Path.Combine(serverDirectory, "server.jar"), "stub server jar");
            return Task.FromResult("server.jar");
        }
    }
}
