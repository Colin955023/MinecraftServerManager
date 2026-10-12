namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 單一伺服器匯入交易結果
/// </summary>
public sealed record ServerImportResult(
    ImportStatus Status,
    string Message = "",
    string Name = "",
    ServerConfig? Config = null,
    IReadOnlyList<string>? Warnings = null,
    IReadOnlyDictionary<string, string>? Evidence = null,
    string DiagnosticId = "",
    bool CleanupComplete = true)
{
    public IReadOnlyList<string> Warnings { get; init; } = Warnings ?? [];
    public IReadOnlyDictionary<string, string> Evidence { get; init; } = Evidence ?? new Dictionary<string, string>();
    public bool Completed => Status == ImportStatus.Completed;

    public static ServerImportResult Success(string name, ServerConfig config, string message = "") =>
        new(ImportStatus.Completed, message, name, config);

    public static ServerImportResult Skipped(string name, string message = "") =>
        new(ImportStatus.Skipped, message, name);

    public static ServerImportResult Cancelled(string name, string message = "") =>
        new(ImportStatus.Cancelled, message, name);

    public static ServerImportResult Failed(string name, string message, string diagnosticId = "", bool cleanupComplete = true) =>
        new(ImportStatus.Failed, message, name, DiagnosticId: diagnosticId, CleanupComplete: cleanupComplete);
}

/// <summary>
/// 批次匯入執行的逐項結果與彙總計數
/// </summary>
public sealed record ServerImportBatchResult(IReadOnlyList<ServerImportResult> Items)
{
    public int CompletedCount => Items.Count(i => i.Completed);
    public int SkippedCount => Items.Count(i => i.Status == ImportStatus.Skipped);
    public int FailedCount => Items.Count(i => i.Status == ImportStatus.Failed);
}
