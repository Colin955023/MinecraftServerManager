namespace MinecraftServerManager.Domain.ValueObjects;

/// <summary>純 ASCII 數字段的數值比較（不溢位）；呼叫端須先去除前導零</summary>
public static class NumericSegmentComparer
{
    /// <summary>先比長度再逐字比較；長度不同即可判定大小，避免轉換為整數溢位</summary>
    public static int Compare(ReadOnlySpan<char> left, ReadOnlySpan<char> right)
    {
        return left.Length != right.Length
            ? left.Length.CompareTo(right.Length)
            : left.SequenceCompareTo(right);
    }
}
