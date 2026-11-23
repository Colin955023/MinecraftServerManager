namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>把子步驟進度換算到整體進度區間</summary>
public static class ProgressMapping
{
    /// <summary>completed／total 對應到 start～end；total 不明時回傳 unknown（預設 start）</summary>
    public static int Map(long completed, long total, int start, int end, int? unknown = null)
    {
        if (total <= 0)
        {
            return unknown ?? start;
        }

        // 先夾限再以 128 位元相乘，避免大檔案位元組數溢位
        long clamped = Math.Clamp(completed, 0, total);
        long offset = (long)((Int128)clamped * (end - start) / total);
        return (int)Math.Clamp(start + offset, Math.Min(start, end), Math.Max(start, end));
    }
}
