using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器玩家設定檔案儲存合約介面 (ops.json, whitelist.json, banned-players.json, banned-ips.json, usercache.json)
/// </summary>
public interface IServerPlayerConfigStore
{
    /// <summary>
    /// 讀取指定伺服器目錄下的所有玩家設定與快取檔案
    /// </summary>
    public Task<ServerPlayerConfigBundle> LoadBundleAsync(string serverPath, CancellationToken cancellationToken = default);

    /// <summary>
    /// 以不可分割原子寫入方式更新指定伺服器目錄下的玩家設定檔案
    /// </summary>
    public Task SaveBundleAsync(string serverPath, ServerPlayerConfigBundle bundle, CancellationToken cancellationToken = default);
}
