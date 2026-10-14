using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;

namespace MinecraftServerManager.App.Collections;

/// <summary>
/// 支援批次更新的 ObservableCollection；批次變更僅發出一次 Reset 通知，減少 UI 重繪次數
/// </summary>
public sealed class BulkObservableCollection<T> : ObservableCollection<T>
{
    /// <summary>
    /// 以單次 Reset 通知取代所有項目
    /// </summary>
    public void ReplaceAll(IEnumerable<T> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        Items.Clear();
        foreach (T item in items)
        {
            Items.Add(item);
        }
        NotifyReset();
    }

    /// <summary>
    /// 以單次 Reset 通知附加多個項目
    /// </summary>
    public void AddRange(IEnumerable<T> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        foreach (T item in items)
        {
            Items.Add(item);
        }
        NotifyReset();
    }

    private void NotifyReset()
    {
        OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
        OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
        OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
    }
}
