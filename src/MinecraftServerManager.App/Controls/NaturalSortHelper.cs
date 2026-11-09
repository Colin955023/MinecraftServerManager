using System.Globalization;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 自然排序輔助工具：日期時間字串依時間比較，其餘依 Windows 數字感知規則比較（容量與下載量等數值欄位由排序鍵直接提供原始數值）
/// </summary>
public static class NaturalSortHelper
{
    /// <summary>
    /// 比對兩個字串之自然排序（日期時間換算為時間戳記比較，不影響 UI 顯示）
    /// </summary>
    public static int CompareNatural(string? x, string? y)
    {
        if (ReferenceEquals(x, y))
        {
            return 0;
        }
        if (x is null)
        {
            return -1;
        }
        if (y is null)
        {
            return 1;
        }

        ReadOnlySpan<char> spanX = x.AsSpan().Trim();
        ReadOnlySpan<char> spanY = y.AsSpan().Trim();

        // 日期時間字串自動統一換算為時間戳記比較
        bool isDateX = TryParseDateTime(spanX, out DateTimeOffset dateX);
        bool isDateY = TryParseDateTime(spanY, out DateTimeOffset dateY);
        if (isDateX || isDateY)
        {
            if (isDateX && isDateY)
            {
                return dateX.CompareTo(dateY);
            }
            if (isDateX && IsPlaceholder(spanY))
            {
                return 1;
            }
            if (isDateY && IsPlaceholder(spanX))
            {
                return -1;
            }
        }

        return CultureInfo.CurrentCulture.CompareInfo.Compare(
            x,
            y,
            CompareOptions.NumericOrdering | CompareOptions.IgnoreCase);
    }

    /// <summary>
    /// 比較兩個排序鍵：null 排最前；皆為字串時採自然排序；同型別可比較時直接比較；其餘以字串自然排序
    /// </summary>
    public static int CompareSortKeys(object? keyX, object? keyY)
    {
        if (keyX is null || keyY is null)
        {
            return keyX is null ? (keyY is null ? 0 : -1) : 1;
        }

        if (keyX is string strX && keyY is string strY)
        {
            return CompareNatural(strX, strY);
        }

        if (keyX.GetType() == keyY.GetType() && keyX is IComparable comparable)
        {
            return comparable.CompareTo(keyY);
        }

        return CompareNatural(
            Convert.ToString(keyX, CultureInfo.InvariantCulture),
            Convert.ToString(keyY, CultureInfo.InvariantCulture));
    }

    private static bool IsPlaceholder(ReadOnlySpan<char> span) =>
        span.IsEmpty || span.SequenceEqual("-") || span.SequenceEqual("未知") || span.SequenceEqual("無");

    private static bool TryParseDateTime(ReadOnlySpan<char> span, out DateTimeOffset result)
    {
        result = default;
        if (span.Length < 8 || !char.IsAsciiDigit(span[0]) || !char.IsAsciiDigit(span[1]) || !char.IsAsciiDigit(span[2]) || !char.IsAsciiDigit(span[3]))
        {
            return false;
        }

        if (span[4] is not ('-' or '/'))
        {
            return false;
        }

        return DateTimeOffset.TryParse(span, CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out result);
    }
}

/// <summary>
/// 純字串的 Windows 自然排序比較器
/// </summary>
public sealed class StringNaturalComparer : IComparer<string>
{
    public static readonly StringNaturalComparer Instance = new();

    public int Compare(string? x, string? y) =>
        NaturalSortHelper.CompareNatural(x, y);
}

/// <summary>
/// 排序鍵比較器（字串採自然排序，同型別 IComparable 直接比較）；配合 <c>OrderBy(keySelector, comparer)</c> 使每筆資料只計算一次排序鍵
/// </summary>
public sealed class SortKeyComparer : IComparer<object?>
{
    public static readonly SortKeyComparer Instance = new();

    public int Compare(object? x, object? y) =>
        NaturalSortHelper.CompareSortKeys(x, y);
}
