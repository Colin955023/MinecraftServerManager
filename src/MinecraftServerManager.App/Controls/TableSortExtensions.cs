using System.Collections.Frozen;
using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;
using Microsoft.UI.Dispatching;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Controls;

/// <summary>表格欄位名稱對應排序鍵選擇器之唯讀對照表（不分大小寫）</summary>
public sealed class SortKeyMap<T>
{
    private readonly FrozenDictionary<string, Func<T, object?>> _selectors;
    private FrozenDictionary<string, Func<T, string?>> _displays = FrozenDictionary<string, Func<T, string?>>.Empty;

    public SortKeyMap(params (string Column, Func<T, object?> Selector)[] entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        _selectors = entries.ToFrozenDictionary(static e => e.Column, static e => e.Selector, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>登錄欄位的顯示文字選擇器，供自動欄寬計算</summary>
    public SortKeyMap<T> WithDisplay(params (string Column, Func<T, string?> Display)[] entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        _displays = entries.ToFrozenDictionary(static e => e.Column, static e => e.Display, StringComparer.OrdinalIgnoreCase);
        return this;
    }

    /// <summary>取得欄位各列的顯示文字；無顯示覆寫時以目前文化格式化排序鍵</summary>
    public IEnumerable<string?> GetDisplayTexts(IEnumerable<T> items, string column)
    {
        if (_displays.TryGetValue(column, out var display))
        {
            return items.Select(display);
        }

        return TryGetSelector(column, out var selector)
            ? items.Select(item => Convert.ToString(selector(item), System.Globalization.CultureInfo.CurrentCulture))
            : [];
    }

    /// <summary>取得指定欄位之排序鍵選擇器</summary>
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

/// <summary>表格排序共用入口</summary>
public static class TableSortExtensions
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(TableSortExtensions));

    /// <summary>依欄位名稱與方向排序；欄位未登錄時不排序並記錄警告</summary>
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
            Logger.Warning("表格排序欄位未登錄排序鍵：{Type}.{Column}", typeof(T).Name, column);
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

    /// <summary>表頭按兩下自動欄寬共用入口：依欄位顯示文字對齊最寬項目；集合為空時不調整</summary>
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
}

/// <summary>表頭排序與自動欄寬的對象</summary>
public interface ITableSortTarget
{
    /// <summary>依欄位與方向排序</summary>
    public void Sort(string column, ListSortDirection direction);

    /// <summary>依內容調整表頭欄寬</summary>
    public void AutoFit(SortableTableHeader header);

    /// <summary>重新監看集合並套用目前排序（頁面自快取還原時使用）；尚未排序時不動作</summary>
    public void Attach();

    /// <summary>解除對集合異動事件的訂閱（頁面卸載時使用）</summary>
    public void Detach();
}

/// <summary>以集合與排序鍵實作的排序對象；記住目前排序，集合重新整理或篩選（新增／重設）後自動重新套用</summary>
/// <param name="items"></param>
/// <param name="keys"></param>
/// <param name="enqueueLow">以低優先權排入 UI 執行緒的委派；預設使用目前執行緒的 DispatcherQueue，測試可注入</param>
public sealed partial class TableSortTarget<T>(Func<ObservableCollection<T>> items, SortKeyMap<T> keys, Func<Action, bool>? enqueueLow = null) : ITableSortTarget
{
    private readonly Func<Action, bool> _enqueueLow = enqueueLow ?? (static action => EnqueueLowOnUiThread(action));
    private ObservableCollection<T>? _observed;
    private string? _column;
    private ListSortDirection _direction;
    private bool _sorting;
    private bool _resortPending;

    public void Sort(string column, ListSortDirection direction)
    {
        _column = column;
        _direction = direction;
        Attach();
    }

    public void Attach()
    {
        if (_column is null)
        {
            return;
        }

        Observe(items());
        ApplySort();
    }

    public void Detach()
    {
        _observed?.CollectionChanged -= OnCollectionChanged;
        _observed = null;
    }

    private void Observe(ObservableCollection<T> collection)
    {
        if (ReferenceEquals(collection, _observed))
        {
            return;
        }

        _observed?.CollectionChanged -= OnCollectionChanged;
        _observed = collection;
        collection.CollectionChanged += OnCollectionChanged;
    }

    private void ApplySort()
    {
        if (_observed is null || _column is null)
        {
            return;
        }

        _sorting = true;
        try
        {
            _observed.SortBy(keys, _column, _direction);
        }
        finally
        {
            _sorting = false;
        }
    }

    /// <summary>集合事件中不可修改集合，合併為一次低優先權重新排序</summary>
    private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (_sorting || _resortPending || e.Action is not (NotifyCollectionChangedAction.Add or NotifyCollectionChangedAction.Reset))
        {
            return;
        }

        _resortPending = _enqueueLow(() =>
        {
            _resortPending = false;
            ApplySort();
        });
    }

    private static bool EnqueueLowOnUiThread(Action action) =>
        DispatcherQueue.GetForCurrentThread()?.TryEnqueue(DispatcherQueuePriority.Low, () => action()) == true;

    public void AutoFit(SortableTableHeader header) => header.AutoFit(items(), keys);
}
