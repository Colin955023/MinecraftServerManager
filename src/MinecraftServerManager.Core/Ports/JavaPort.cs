namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// Java 執行環境詳細資訊
/// </summary>
public sealed record JavaRuntimeInfo(
    string ExecutablePath,
    int MajorVersion,
    bool Is64Bit = true,
    string? JavawPath = null,
    string? Vendor = null);

/// <summary>
/// Java 執行環境偵測器抽象介面
/// </summary>
public interface IJavaRuntimeDetector
{
    /// <summary>
    /// 偵測本機已安裝的 Java 執行環境清單
    /// </summary>
    public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 依據指定的 Java 主要版本尋找最合適的執行環境
    /// </summary>
    public Task<JavaRuntimeInfo?> FindBestMatchAsync(
        int targetMajor,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Java 自動安裝器抽象介面
/// </summary>
public interface IJavaInstaller
{
    /// <summary>
    /// 檢查系統環境是否支援 winget
    /// </summary>
    public Task<bool> IsWingetAvailableAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// 透過 winget 安裝指定主要版本的 Java
    /// </summary>
    public Task<ProcessExitResult> InstallWithWingetAsync(
        int majorVersion,
        CancellationToken cancellationToken = default);
}

