using System.Collections;
using System.Collections.Concurrent;
using System.ComponentModel;
using System.Globalization;
using System.Reflection;
using LinqExpression = System.Linq.Expressions.Expression;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;

namespace MinecraftServerManager.App.Behaviors;

/// <summary>
/// 提供 DataGrid 欄位標頭點選時套用 Windows 檔案總管自然排序（Natural Sort）之附加行為
/// </summary>
public static class DataGridNaturalSortBehavior
{
    public static readonly DependencyProperty EnableNaturalSortProperty =
        DependencyProperty.RegisterAttached(
            "EnableNaturalSort",
            typeof(bool),
            typeof(DataGridNaturalSortBehavior),
            new PropertyMetadata(false, OnEnableChanged));

    public static bool GetEnableNaturalSort(DependencyObject obj) =>
        (bool)obj.GetValue(EnableNaturalSortProperty);

    public static void SetEnableNaturalSort(DependencyObject obj, bool value) =>
        obj.SetValue(EnableNaturalSortProperty, value);

    private static void OnEnableChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is DataGrid dataGrid)
        {
            dataGrid.Sorting -= OnDataGridSorting;
            if ((bool)e.NewValue)
            {
                dataGrid.Sorting += OnDataGridSorting;
            }
        }
    }

    private static void OnDataGridSorting(object sender, DataGridSortingEventArgs e)
    {
        if (sender is not DataGrid dataGrid || !GetEnableNaturalSort(dataGrid))
        {
            return;
        }

        var column = e.Column;
        if (column is null)
        {
            return;
        }

        e.Handled = true;

        var direction = column.SortDirection != ListSortDirection.Ascending
            ? ListSortDirection.Ascending
            : ListSortDirection.Descending;

        // 清除其他欄位箭頭，指派目前欄位排序方向
        foreach (var col in dataGrid.Columns)
        {
            if (!ReferenceEquals(col, column))
            {
                col.SortDirection = null;
            }
        }
        column.SortDirection = direction;

        if (CollectionViewSource.GetDefaultView(dataGrid.ItemsSource) is ListCollectionView view)
        {
            string sortMember = column.SortMemberPath;
            if (string.IsNullOrWhiteSpace(sortMember) && column is DataGridBoundColumn boundCol && boundCol.Binding is Binding b)
            {
                sortMember = b.Path?.Path ?? string.Empty;
            }

            if (!string.IsNullOrWhiteSpace(sortMember))
            {
                view.CustomSort = new WindowsNaturalSortComparer(sortMember, direction);
            }
        }
    }
}

/// <summary>
/// 依據 .NET 10 CompareOptions.NumericOrdering 之自然排序比較器
/// </summary>
public sealed class WindowsNaturalSortComparer(string propertyName, ListSortDirection direction) : IComparer
{
    private static readonly ConcurrentDictionary<(Type, string), Func<object, object?>?> GetterCache = new();

    public int Compare<T>(T? x, T? y) => Compare(x, (object?)y);

    public int Compare(object? x, object? y)
    {
        if (ReferenceEquals(x, y))
        {
            return 0;
        }
        if (x is null)
        {
            return direction == ListSortDirection.Ascending ? -1 : 1;
        }
        if (y is null)
        {
            return direction == ListSortDirection.Ascending ? 1 : -1;
        }

        int result = CompareValues(x, y);
        return direction == ListSortDirection.Ascending ? result : -result;
    }

    private int CompareValues(object x, object y)
    {
        // 檔案大小特殊最佳化：若物件具有 RawFileSize，優先採用數值比較
        if (string.Equals(propertyName, "FileSize", StringComparison.OrdinalIgnoreCase))
        {
            long? rawX = GetPropertyValue<long>(x, "RawFileSize");
            long? rawY = GetPropertyValue<long>(y, "RawFileSize");
            if (rawX.HasValue && rawY.HasValue)
            {
                return rawX.Value.CompareTo(rawY.Value);
            }
        }

        // 下載量特殊最佳化：若物件具有 DownloadCountRaw，優先採用數值比較
        if (string.Equals(propertyName, "Downloads", StringComparison.OrdinalIgnoreCase))
        {
            long? rawX = GetPropertyValue<long>(x, "DownloadCountRaw");
            long? rawY = GetPropertyValue<long>(y, "DownloadCountRaw");
            if (rawX.HasValue && rawY.HasValue)
            {
                return rawX.Value.CompareTo(rawY.Value);
            }
        }

        object? valX = GetPropertyValue(x, propertyName);
        object? valY = GetPropertyValue(y, propertyName);

        if (valX is null && valY is null)
        {
            return 0;
        }
        if (valX is null)
        {
            return -1;
        }
        if (valY is null)
        {
            return 1;
        }

        if (valX is string strX && valY is string strY)
        {
            return CultureInfo.CurrentCulture.CompareInfo.Compare(
                strX,
                strY,
                CompareOptions.NumericOrdering | CompareOptions.IgnoreCase);
        }

        if (valX is IComparable compX)
        {
            try
            {
                return compX.CompareTo(valY);
            }
            catch
            {
            }
        }

        return string.Compare(valX.ToString(), valY.ToString(), StringComparison.OrdinalIgnoreCase);
    }

    private static Func<object, object?>? CreateGetter(Type type, string propName)
    {
        var prop = type.GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
        if (prop is null || !prop.CanRead)
        {
            return null;
        }

        var param = LinqExpression.Parameter(typeof(object), "obj");
        var castParam = LinqExpression.Convert(param, type);
        var propAccess = LinqExpression.Property(castParam, prop);
        var castResult = LinqExpression.Convert(propAccess, typeof(object));
        return LinqExpression.Lambda<Func<object, object?>>(castResult, param).Compile();
    }

    private static object? GetPropertyValue(object target, string propName)
    {
        var type = target.GetType();
        var getter = GetterCache.GetOrAdd((type, propName), static key => CreateGetter(key.Item1, key.Item2));
        return getter?.Invoke(target);
    }

    private static T? GetPropertyValue<T>(object target, string propName) where T : struct
    {
        object? val = GetPropertyValue(target, propName);
        if (val is T typed)
        {
            return typed;
        }
        return null;
    }
}
