namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器建立交易的最終狀態與診斷資訊
/// </summary>
public sealed record ServerCreationResult(
    CreationStatus Status,
    string Message = "",
    ServerConfig? Config = null,
    string DiagnosticId = "",
    bool CleanupComplete = true)
{
    public bool Completed => Status == CreationStatus.Completed;

    public static ServerCreationResult Success(ServerConfig config, string message = "") =>
        new(CreationStatus.Completed, message, config);

    public static ServerCreationResult Cancelled(string message = "", bool cleanupComplete = true) =>
        new(CreationStatus.Cancelled, message, CleanupComplete: cleanupComplete);

    public static ServerCreationResult Failed(string message, string diagnosticId = "", bool cleanupComplete = true) =>
        new(CreationStatus.Failed, message, DiagnosticId: diagnosticId, CleanupComplete: cleanupComplete);
}
