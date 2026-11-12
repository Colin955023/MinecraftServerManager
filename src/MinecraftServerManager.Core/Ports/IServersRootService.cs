using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器存放根目錄路徑檢查與資料遷移抽象介面</summary>
public interface IServersRootService
{
    /// <summary>驗證新設定之伺服器存放根目錄並回傳正規化後路徑</summary>
    public ServersRootCheck ValidateTargetRoot(string? currentRoot, string? newRoot);

    /// <summary>檢查原伺服器根目錄是否存放有伺服器或檔案</summary>
    public Task<bool> HasStoredContentAsync(string? currentRoot, CancellationToken cancellationToken = default);

    /// <summary>檢查遷移目標目錄是否不存在或為空資料夾</summary>
    public Task<bool> IsTargetDirectoryEmptyAsync(string? targetRoot, CancellationToken cancellationToken = default);

    /// <summary>將舊根目錄內所有內容遷移至新根目錄，失敗時自動復原</summary>
    public Task RelocateAllContentAsync(
        string currentRoot,
        string newRoot,
        IProgress<(int Percent, string Message)>? progress = null,
        CancellationToken cancellationToken = default);
}
