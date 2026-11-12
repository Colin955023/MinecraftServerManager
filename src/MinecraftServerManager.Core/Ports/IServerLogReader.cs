namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器記錄檔讀取抽象介面</summary>
public interface IServerLogReader
{
    /// <summary>讀取 logs/latest.log 尾端內容（受大小與行數上限限制並去除 ANSI 色碼）；無檔案或讀取失敗時回傳空清單</summary>
    public Task<IReadOnlyList<string>> ReadLatestLogTailAsync(string serverPath, CancellationToken cancellationToken = default);
}
