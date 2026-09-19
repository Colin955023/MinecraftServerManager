using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器載入器下載與安裝執行抽象介面
/// </summary>
public interface ILoaderInstallerService
{
    /// <summary>
    /// 執行指定 Loader 的下載與安裝流程，並回傳主要啟動目標檔名（如 run.bat 或 server.jar）
    /// </summary>
    public Task<string> InstallLoaderAsync(
        LoaderKind loader,
        string minecraftVersion,
        string loaderVersion,
        string serverDirectory,
        string javaExecutablePath,
        IProgress<LoaderInstallProgress>? progress = null,
        CancellationToken cancellationToken = default);
}
