using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.TestSupport;

/// <summary>
/// 測試用載入器安裝器：不連網，只在伺服器目錄寫入佔位 server.jar
/// </summary>
internal sealed class StubLoaderInstaller : ILoaderInstallerService
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
