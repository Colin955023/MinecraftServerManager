using System.Collections.Frozen;
using System.Collections.ObjectModel;
using System.ComponentModel;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 表格欄位名稱對應排序鍵選擇器之唯讀對照表（不分大小寫）
/// </summary>
public sealed class SortKeyMap<T>
{
    private readonly FrozenDictionary<string, Func<T, object?>> _selectors;
    private FrozenDictionary<string, Func<T, string?>> _displays = FrozenDictionary<string, Func<T, string?>>.Empty;

    public SortKeyMap(params (string Column, Func<T, object?> Selector)[] entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        _selectors = entries.ToFrozenDictionary(static e => e.Column, static e => e.Selector, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    /// 登錄排序鍵非顯示文字之欄位（如原始位元組數）所對應的顯示文字選擇器，供自動欄寬計算
    /// </summary>
    public SortKeyMap<T> WithDisplay(params (string Column, Func<T, string?> Display)[] entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        _displays = entries.ToFrozenDictionary(static e => e.Column, static e => e.Display, StringComparer.OrdinalIgnoreCase);
        return this;
    }

    /// <summary>
    /// 取得指定欄位各列之顯示文字：優先使用顯示文字選擇器，否則採字串型別之排序鍵，其餘欄位僅以表頭文字計算
    /// </summary>
    public IEnumerable<string?> GetDisplayTexts(IEnumerable<T> items, string column)
    {
        if (_displays.TryGetValue(column, out var display))
        {
            return items.Select(display);
        }

        return TryGetSelector(column, out var selector) ? items.Select(item => selector(item) as string) : [];
    }

    /// <summary>
    /// 取得指定欄位之排序鍵選擇器
    /// </summary>
    public bool TryGetSelector(string column, out Func<T, object?> selector)
    {
        if (!string.IsNullOrEmpty(column) && _selectors.TryGetValue(column, out var found))
        {
            selector = found;
            return true;
        }

        selector = static _ => null;
        return false;
    }
}

/// <summary>
/// 表格欄位排序的唯一共用入口：以型別化排序鍵與 Windows 自然排序規則重新排列可觀察集合
/// </summary>
public static class TableSortExtensions
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(TableSortExtensions));

    /// <summary>
    /// 依欄位名稱與方向排序集合；BulkObservableCollection 以單次 Reset 通知整批替換。欄位未登錄時不排序並記錄警告
    /// </summary>
    public static void SortBy<T>(this ObservableCollection<T> items, SortKeyMap<T> keys, string column, ListSortDirection direction)
    {
        ArgumentNullException.ThrowIfNull(items);
        ArgumentNullException.ThrowIfNull(keys);
        if (items.Count <= 1 || string.IsNullOrEmpty(column))
        {
            return;
        }

        if (!keys.TryGetSelector(column, out var selector))
        {
            Logger.Warning("表格排序欄位未登錄排序鍵: {Type}.{Column}", typeof(T).Name, column);
            return;
        }

        List<T> sorted = direction == ListSortDirection.Ascending
            ? [.. items.OrderBy(selector, SortKeyComparer.Instance)]
            : [.. items.OrderByDescending(selector, SortKeyComparer.Instance)];
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
    /// 表頭點兩下自動欄寬的唯一共用入口：依欄位顯示文字對齊最寬項目；集合為空時不調整
    /// </summary>
    public static void AutoFit<T>(this SortableTableHeader header, IReadOnlyCollection<T> items, SortKeyMap<T> keys)
    {
        ArgumentNullException.ThrowIfNull(header);
        ArgumentNullException.ThrowIfNull(items);
        ArgumentNullException.ThrowIfNull(keys);
        if (items.Count > 0)
        {
            header.FitToContent(keys.GetDisplayTexts(items, header.SortPropertyName));
        }
    }

    /// <summary>
    /// 依表頭排序事件參數排序集合
    /// </summary>
    public static void SortBy<T>(this ObservableCollection<T> items, SortKeyMap<T> keys, SortRequestedEventArgs request)
    {
        ArgumentNullException.ThrowIfNull(request);
        items.SortBy(keys, request.PropertyName, request.Direction);
    }
}
