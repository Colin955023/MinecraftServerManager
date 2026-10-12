namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 模組檔案操作結果（下載、覆蓋與回復狀態）
/// </summary>
public sealed record ModFileOperationResult(
    string Status,
    string? FinalPath = null,
    bool RollbackPerformed = false,
    string Message = "")
{
    public bool Completed => string.Equals(Status, "completed", StringComparison.OrdinalIgnoreCase);
    public bool Cancelled => string.Equals(Status, "cancelled", StringComparison.OrdinalIgnoreCase);
    public bool Failed => string.Equals(Status, "failed", StringComparison.OrdinalIgnoreCase);

    public static ModFileOperationResult Success(string finalPath, string message = "") =>
        new("completed", finalPath, false, message);

    public static ModFileOperationResult Cancel(string message = "", bool rollbackPerformed = false) =>
        new("cancelled", null, rollbackPerformed, message);

    public static ModFileOperationResult Fail(string message, bool rollbackPerformed = false) =>
        new("failed", null, rollbackPerformed, message);
}

/// <summary>
/// 本地模組檔案異動結果（啟用、停用、刪除等批次操作）
/// </summary>
public sealed record LocalModMutationResult(
    string Status,
    string Title = "",
    string Message = "",
    string? FinalPath = null,
    int AffectedCount = 0,
    IReadOnlyList<string>? MissingIds = null)
{
    public IReadOnlyList<string> MissingIds { get; init; } = MissingIds ?? [];

    public bool Completed => string.Equals(Status, "completed", StringComparison.OrdinalIgnoreCase);
    public bool Partial => string.Equals(Status, "partial", StringComparison.OrdinalIgnoreCase);
    public bool Failed => string.Equals(Status, "failed", StringComparison.OrdinalIgnoreCase);

    public static LocalModMutationResult Success(string title = "", string message = "", string? finalPath = null, int affectedCount = 1) =>
        new("completed", title, message, finalPath, affectedCount);

    public static LocalModMutationResult Failure(string title, string message, IEnumerable<string>? missingIds = null) =>
        new("failed", title, message, null, 0, missingIds?.ToArray());

    public static LocalModMutationResult PartialSuccess(string title, string message, int affectedCount, IEnumerable<string>? missingIds = null) =>
        new("partial", title, message, null, affectedCount, missingIds?.ToArray());
}
