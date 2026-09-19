using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 模組管理外觀服務抽象介面
/// </summary>
public interface IModManager
{
    /// <summary>
    /// 取得指定伺服器的模組清單
    /// </summary>
    public Task<IReadOnlyList<LocalModInfo>> GetModsAsync(
        string serverDirectory,
        bool includeDisabled = true,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 切換模組啟用或停用狀態
    /// </summary>
    public Task<LocalModMutationResult> SetModStateAsync(
        string serverDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 刪除指定模組
    /// </summary>
    public Task<LocalModMutationResult> DeleteModsAsync(
        string serverDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 匯入外部本機模組檔案
    /// </summary>
    public Task<LocalModMutationResult> ImportModAsync(
        string serverDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 下載並安裝線上模組
    /// </summary>
    public Task<ModFileOperationResult> InstallOnlineModAsync(
        string serverDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// 匯出模組清單為文字、JSON 或 HTML 格式
    /// </summary>
    public Task<string> ExportModListAsync(
        string serverDirectory,
        string format = "text",
        CancellationToken cancellationToken = default);
}
