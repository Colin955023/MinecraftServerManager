namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>把子步驟進度換算到整體進度區間</summary>
public static class ProgressMapping
{
    /// <summary>completed／total 對應到 start～end；total 不明時回傳 unknown（預設 start）</summary>
    public static int Map(long completed, long total, int start, int end, int? unknown = null) =>
        total > 0
            ? Math.Clamp((int)(start + (completed * (end - start) / total)), start, end)
            : unknown ?? start;
}
