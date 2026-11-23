namespace MinecraftServerManager.Core.Ports;

/// <summary>Java 自動安裝器介面</summary>
public interface IJavaInstaller
{
    /// <summary>透過 winget 安裝指定主要版本的 Java</summary>
    public Task<ProcessExitResult> InstallWithWingetAsync(
        int majorVersion,
        CancellationToken cancellationToken = default);
}
