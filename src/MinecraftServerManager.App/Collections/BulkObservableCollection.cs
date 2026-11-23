using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;

namespace MinecraftServerManager.App.Collections;

/// <summary>支援批次更新的集合；整批取代或超量修剪只發一次 Reset 通知</summary>
public sealed partial class BulkObservableCollection<T> : ObservableCollection<T>
{
    private static readonly PropertyChangedEventArgs CountChangedArgs = new(nameof(Count));
    private static readonly PropertyChangedEventArgs IndexerChangedArgs = new("Item[]");
    private static readonly NotifyCollectionChangedEventArgs ResetArgs = new(NotifyCollectionChangedAction.Reset);

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

        // 先具體化：來源可能是以本集合為基礎的延遲查詢，清空後才列舉會得到空結果
        List<T> snapshot = [.. items];
        if (snapshot.Count == 0 && Count == 0)
        {
            return;
        }

        CheckReentrancy();
        Items.Clear();
        AddRangeToItems(snapshot, 0);
        RaiseReset();
    }

    /// <summary>批次移除指定項目；若有項目被移除則發出單次 Reset 通知</summary>
    public void RemoveRange(IEnumerable<T> items)
    {
        ArgumentNullException.ThrowIfNull(items);

        List<T> toRemove = items as List<T> ?? items.ToList();
        if (toRemove.Count == 0 || Count == 0)
        {
            return;
        }

        CheckReentrancy();
        bool changed = false;
        if (Items is List<T> list)
        {
            if (toRemove.Count > 4)
            {
                HashSet<T> set = [.. toRemove];
                changed = list.RemoveAll(set.Contains) > 0;
            }
            else
            {
                for (int i = 0; i < toRemove.Count; i++)
                {
                    if (list.Remove(toRemove[i]))
                    {
                        changed = true;
                    }
                }
            }
        }
        else
        {
            for (int i = 0; i < toRemove.Count; i++)
            {
                if (Items.Remove(toRemove[i]))
                {
                    changed = true;
                }
            }
        }

        if (changed)
        {
            RaiseReset();
        }
    }

    /// <summary>附加項目；總數超過 <paramref name="maxCount"/> 時自前端修剪至 <paramref name="targetCount"/> 並只發一次 Reset</summary>
    public void AppendAndTrim(IEnumerable<T> items, int maxCount, int targetCount)
    {
        ArgumentNullException.ThrowIfNull(items);
        ArgumentOutOfRangeException.ThrowIfLessThan(maxCount, 1);
        ArgumentOutOfRangeException.ThrowIfNegative(targetCount);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(targetCount, maxCount);

        IReadOnlyList<T> incoming = items as IReadOnlyList<T> ?? items.ToList();
        if (incoming.Count == 0)
        {
            return;
        }

        if (Count + incoming.Count <= maxCount)
        {
            for (int i = 0; i < incoming.Count; i++)
            {
                Add(incoming[i]);
            }

            return;
        }

        CheckReentrancy();
        int keepFromIncoming = Math.Min(incoming.Count, targetCount);
        int keepFromExisting = Math.Min(Count, targetCount - keepFromIncoming);
        RemoveFromFront(Count - keepFromExisting);
        AddRangeToItems(incoming, incoming.Count - keepFromIncoming);
        RaiseReset();
    }

    private void RemoveFromFront(int count)
    {
        if (count <= 0)
        {
            return;
        }

        if (Items is List<T> list)
        {
            list.RemoveRange(0, count);
            return;
        }

        for (int i = 0; i < count; i++)
        {
            Items.RemoveAt(0);
        }
    }

    private void AddRangeToItems(IReadOnlyList<T> source, int startIndex)
    {
        if (Items is List<T> list)
        {
            list.EnsureCapacity(list.Count + source.Count - startIndex);
        }

        for (int i = startIndex; i < source.Count; i++)
        {
            Items.Add(source[i]);
        }
    }

    private void RaiseReset()
    {
        OnPropertyChanged(CountChangedArgs);
        OnPropertyChanged(IndexerChangedArgs);
        OnCollectionChanged(ResetArgs);
    }
}
