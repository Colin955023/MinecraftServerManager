namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器記錄檔讀取介面</summary>
public interface IServerLogReader
{
    /// <summary>讀取 logs/latest.log 尾端；無檔案或失敗回傳空清單</summary>
    public Task<IReadOnlyList<string>> ReadLatestLogTailAsync(string serverPath, CancellationToken cancellationToken = default);
}
