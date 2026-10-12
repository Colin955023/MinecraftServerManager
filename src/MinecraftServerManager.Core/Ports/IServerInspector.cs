using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 伺服器目錄內容與健全度檢查抽象介面
/// </summary>
public interface IServerInspector
{
    /// <summary>
    /// 執行伺服器目錄檢查並產生不可變診斷快照
    /// </summary>
    public Task<ServerInspection> InspectAsync(
        string serverDirectory,
        ServerInspectionIntent? intent = null,
        CancellationToken cancellationToken = default);
}
