using System.Collections.ObjectModel;
using System.ComponentModel;
using MinecraftServerManager.App.Collections;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 表格欄位排序的唯一共用入口：以 Windows 自然排序規則重新排列可觀察集合
/// </summary>
public static class TableSortExtensions
{
    /// <summary>
    /// 依屬性名稱與方向排序集合；BulkObservableCollection 以單次 Reset 通知整批替換
    /// </summary>
    public static void SortBy<T>(this ObservableCollection<T> items, string propertyName, ListSortDirection direction)
    {
        ArgumentNullException.ThrowIfNull(items);
        if (items.Count <= 1 || string.IsNullOrEmpty(propertyName))
        {
            return;
        }

        List<T> sorted = [.. items.Order(new WindowsNaturalSortComparer<T>(propertyName, direction))];
        if (items is BulkObservableCollection<T> bulk)
        {
            bulk.ReplaceAll(sorted);
            return;
        }

        items.Clear();
        foreach (T item in sorted)
        {
            items.Add(item);
        }
    }

    /// <summary>
    /// 依表頭排序事件參數排序集合
    /// </summary>
    public static void SortBy<T>(this ObservableCollection<T> items, SortRequestedEventArgs request)
    {
        ArgumentNullException.ThrowIfNull(request);
        items.SortBy(request.PropertyName, request.Direction);
    }
}
