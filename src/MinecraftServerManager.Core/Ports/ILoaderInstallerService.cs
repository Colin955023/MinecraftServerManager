using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器載入器下載與安裝執行介面</summary>
public interface ILoaderInstallerService
{
    /// <summary>下載並安裝載入器，回傳啟動目標檔名</summary>
    public Task<string> InstallLoaderAsync(
        LoaderKind loader,
        string minecraftVersion,
        string loaderVersion,
        string serverDirectory,
        string javaExecutablePath,
        IProgress<LoaderInstallProgress>? progress = null,
        CancellationToken cancellationToken = default);
}
