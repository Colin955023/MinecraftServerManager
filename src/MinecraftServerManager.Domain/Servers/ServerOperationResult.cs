namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器操作結果（供 UI 層與工作流程呈現結果）
/// </summary>
public sealed record ServerOperationResult(
    bool Success,
    string Message = "",
    string Title = "",
    string ServerName = "")
{
    public bool Failed => !Success;

    public static ServerOperationResult Ok(string message = "", string title = "", string serverName = "") =>
        new(true, message, title, serverName);

    public static ServerOperationResult Fail(string message, string title = "", string serverName = "") =>
        new(false, message, title, serverName);
}
