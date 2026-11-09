using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;

namespace MinecraftServerManager.App.Collections;

/// <summary>
/// 支援批次更新的 ObservableCollection；整批取代僅發出一次 Reset 通知，減少 UI 重繪次數
/// </summary>
public sealed partial class BulkObservableCollection<T> : ObservableCollection<T>
{
    public BulkObservableCollection()
    {
    }

    public BulkObservableCollection(IEnumerable<T> collection)
        : base(collection)
    {
    }

    /// <summary>
    /// 以單次 Reset 通知取代所有項目
    /// </summary>
    public void ReplaceAll(IEnumerable<T> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        if (Items is List<T> list)
        {
            list.Clear();
            list.AddRange(items);
        }
        else
        {
            Items.Clear();
            foreach (T item in items)
            {
                Items.Add(item);
            }
        }

        OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
        OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
        OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
    }

    /// <summary>
    /// 逐筆附加項目，超過上限時自前端修剪至目標數量；使用增量通知，清單只插入新列而不整批重建
    /// </summary>
    public void AppendAndTrim(IEnumerable<T> items, int maxCount, int targetCount)
    {
        ArgumentNullException.ThrowIfNull(items);
        foreach (T item in items)
        {
            Add(item);
        }

        if (Count > maxCount)
        {
            for (int i = Count - targetCount; i > 0; i--)
            {
                RemoveAt(0);
            }
        }
    }
}
