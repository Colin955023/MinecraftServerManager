using System.Collections.Specialized;
using MinecraftServerManager.App.Collections;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class BulkObservableCollectionTests
{
    [Fact]
    public void ReplaceAll_ReplacesItemsAndFiresSingleResetEvent()
    {
        var col = new BulkObservableCollection<int> { 1, 2, 3 };
        int resetCount = 0;
        col.CollectionChanged += (s, e) =>
        {
            if (e.Action == NotifyCollectionChangedAction.Reset)
            {
                resetCount++;
            }
        };

        col.ReplaceAll([10, 20, 30, 40]);

        Assert.Equal([10, 20, 30, 40], col);
        Assert.Equal(1, resetCount);
    }

    [Fact]
    public void AppendAndTrim_TrimsFromFrontWithIncrementalNotifications()
    {
        var col = new BulkObservableCollection<int>();
        int resetCount = 0;
        col.CollectionChanged += (s, e) =>
        {
            if (e.Action == NotifyCollectionChangedAction.Reset)
            {
                resetCount++;
            }
        };

        // 加入 10 個項目，maxCount = 6, targetCount = 4
        col.AppendAndTrim(Enumerable.Range(1, 10), maxCount: 6, targetCount: 4);

        Assert.Equal(4, col.Count);
        // 保留的是最後 4 個元素：7, 8, 9, 10
        Assert.Equal([7, 8, 9, 10], col);
        Assert.Equal(0, resetCount);
    }
}
