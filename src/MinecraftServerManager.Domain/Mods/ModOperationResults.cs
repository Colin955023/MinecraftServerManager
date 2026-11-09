namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 模組操作結果狀態
/// </summary>
public enum ModOperationStatus
{
    Completed,
    Partial,
    Cancelled,
    Failed,
}

/// <summary>
/// 模組檔案操作結果（下載、覆蓋與回復狀態）
/// </summary>
public sealed record ModFileOperationResult(
    ModOperationStatus Status,
    string? FinalPath = null,
    string Message = "")
{
    public bool Completed => Status == ModOperationStatus.Completed;
    public bool Failed => Status == ModOperationStatus.Failed;

    public static ModFileOperationResult Success(string finalPath, string message = "") =>
        new(ModOperationStatus.Completed, finalPath, message);

    public static ModFileOperationResult Cancel(string message = "") =>
        new(ModOperationStatus.Cancelled, null, message);

    public static ModFileOperationResult Fail(string message) =>
        new(ModOperationStatus.Failed, null, message);
}

/// <summary>
/// 本地模組檔案異動結果（啟用、停用、刪除等批次操作）
/// </summary>
public sealed record LocalModMutationResult(
    ModOperationStatus Status,
    string Title = "",
    string Message = "",
    string? FinalPath = null,
    int AffectedCount = 0)
{
    public bool Completed => Status == ModOperationStatus.Completed;
    public bool Partial => Status == ModOperationStatus.Partial;
    public bool Failed => Status == ModOperationStatus.Failed;

    public static LocalModMutationResult Success(string title = "", string message = "", string? finalPath = null, int affectedCount = 1) =>
        new(ModOperationStatus.Completed, title, message, finalPath, affectedCount);

    public static LocalModMutationResult Failure(string title, string message) =>
        new(ModOperationStatus.Failed, title, message, null, 0);
}
