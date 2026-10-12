using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 模組檔案異動、啟停、刪除與交易安裝抽象介面
/// </summary>
public interface IModFileInstaller
{
    /// <summary>
    /// 切換本地模組啟用或停用狀態
    /// </summary>
    public Task<LocalModMutationResult> SetModStateAsync(
        string modsDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 批次刪除指定模組檔案
    /// </summary>
    public Task<LocalModMutationResult> DeleteModsAsync(
        string modsDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 匯入外部本機 JAR 檔案至 mods 目錄
    /// </summary>
    public Task<LocalModMutationResult> ImportLocalModAsync(
        string modsDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 遠端下載並以原子交易方式安裝模組檔案
    /// </summary>
    public Task<ModFileOperationResult> InstallRemoteModAsync(
        string modsDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default);
}
