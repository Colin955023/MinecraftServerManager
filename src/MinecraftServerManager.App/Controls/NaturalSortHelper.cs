using System.Globalization;

namespace MinecraftServerManager.App.Controls;

/// <summary>自然排序輔助工具：字串依 .NET 10 原生 <see cref="CompareOptions.NumericOrdering"/> 比較，數值與時間戳記欄位由排序鍵直接提供原始數值</summary>
public static class NaturalSortHelper
{
    /// <summary>數字感知且忽略大小寫之字串自然排序比較器</summary>
    public static StringComparer StringComparer { get; } =
        StringComparer.Create(CultureInfo.CurrentCulture, CompareOptions.NumericOrdering | CompareOptions.IgnoreCase);

    /// <summary>比較兩個排序鍵：null 排最前；皆為字串時採自然排序；同型別可比較時直接比較；其餘以字串自然排序</summary>
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

/// <summary>排序鍵比較器（字串採自然排序，同型別 IComparable 直接比較）；配合 <c>OrderBy(keySelector, comparer)</c> 使每筆資料只計算一次排序鍵</summary>
public sealed class SortKeyComparer : IComparer<object?>
{
    public static readonly SortKeyComparer Instance = new();

    public int Compare(object? x, object? y) =>
        NaturalSortHelper.CompareSortKeys(x, y);
}
