using System.Globalization;

namespace MinecraftServerManager.App.Controls;

/// <summary>自然排序：字串以 <see cref="CompareOptions.NumericOrdering"/> 比較</summary>
public static class NaturalSortHelper
{
    /// <summary>數字感知且忽略大小寫之字串自然排序比較器</summary>
    public static StringComparer StringComparer { get; } =
        StringComparer.Create(CultureInfo.CurrentCulture, CompareOptions.NumericOrdering | CompareOptions.IgnoreCase);

    /// <summary>比較排序鍵：null 最前；字串採自然排序；同型別直接比較</summary>
    public static int CompareSortKeys(object? keyX, object? keyY)
    {
        if (keyX is null || keyY is null)
        {
            return keyX is null ? (keyY is null ? 0 : -1) : 1;
        }

        if (keyX is string strX && keyY is string strY)
        {
            return StringComparer.Compare(strX, strY);
        }

        if (keyX.GetType() == keyY.GetType() && keyX is IComparable comparable)
        {
            return comparable.CompareTo(keyY);
        }

        return StringComparer.Compare(
            Convert.ToString(keyX, CultureInfo.InvariantCulture),
            Convert.ToString(keyY, CultureInfo.InvariantCulture));
    }
}

/// <summary>排序鍵比較器，供 <c>OrderBy(keySelector, comparer)</c> 使用</summary>
public sealed class SortKeyComparer : IComparer<object?>
{
    public static readonly SortKeyComparer Instance = new();

    public int Compare(object? x, object? y) =>
        NaturalSortHelper.CompareSortKeys(x, y);
}
