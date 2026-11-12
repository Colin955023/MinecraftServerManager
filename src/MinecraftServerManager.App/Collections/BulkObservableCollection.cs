using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;

namespace MinecraftServerManager.App.Collections;

/// <summary>支援批次更新的 ObservableCollection；整批取代僅發出一次 Reset 通知，減少 UI 重繪次數</summary>
public sealed partial class BulkObservableCollection<T> : ObservableCollection<T>
{
    public BulkObservableCollection()
    {
    }

    public BulkObservableCollection(IEnumerable<T> collection)
        : base(collection)
    {
    }

    /// <summary>以單次 Reset 通知取代所有項目</summary>
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

    /// <summary>逐筆附加項目，超過上限時自前端修剪至目標數量；使用增量通知，清單只插入新列而不整批重建</summary>
    public void AppendAndTrim(IEnumerable<T> items, int maxCount, int targetCount)
    {
        ArgumentNullException.ThrowIfNull(items);
        IReadOnlyList<T> incoming = items as IReadOnlyList<T> ?? items.ToList();
        if (incoming.Count == 0)
        {
            return;
        }

        int total = Count + incoming.Count;
        int startIndex = 0;
        if (total > maxCount)
        {
            int keepFromIncoming = Math.Min(incoming.Count, targetCount);
            int keepFromExisting = Math.Max(0, targetCount - keepFromIncoming);
            int removeFromExisting = Count - keepFromExisting;
            for (int i = 0; i < removeFromExisting; i++)
            {
                RemoveAt(0);
            }

            startIndex = incoming.Count - keepFromIncoming;
        }

        for (int i = startIndex; i < incoming.Count; i++)
        {
            Add(incoming[i]);
        }
    }
}
