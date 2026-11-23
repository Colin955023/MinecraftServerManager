using System.Collections.Specialized;
using MinecraftServerManager.App.Collections;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class BulkObservableCollectionTests
{
    [Fact]
    public void ReplaceAll_NewItems_FiresSingleReset()
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
    public void AppendAndTrim_OverHighWatermark_TrimsWithSingleReset()
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
        Assert.Equal(1, resetCount);
    }

    [Fact]
    public void AppendAndTrim_BelowHighWatermark_AddsIncrementally()
    {
        var col = new BulkObservableCollection<int> { 1 };
        var actions = new List<NotifyCollectionChangedAction>();
        col.CollectionChanged += (s, e) => actions.Add(e.Action);

        col.AppendAndTrim([2, 3], maxCount: 6, targetCount: 4);

        Assert.Equal([1, 2, 3], col);
        Assert.Equal([NotifyCollectionChangedAction.Add, NotifyCollectionChangedAction.Add], actions);
    }

    [Fact]
    public void AppendAndTrim_SmallIncoming_KeepsExistingTail()
    {
        var col = new BulkObservableCollection<int>([1, 2, 3, 4, 5]);

        col.AppendAndTrim([6, 7], maxCount: 6, targetCount: 4);

        Assert.Equal([4, 5, 6, 7], col);
    }

    [Theory]
    [InlineData(0, 0)]
    [InlineData(5, 6)]
    [InlineData(5, -1)]
    public void AppendAndTrim_InvalidWatermarks_Throws(int maxCount, int targetCount)
    {
        var col = new BulkObservableCollection<int>();
        Assert.Throws<ArgumentOutOfRangeException>(() => col.AppendAndTrim([1], maxCount, targetCount));
    }

    [Fact]
    public void ReplaceAll_EmptyToEmpty_RaisesNothing()
    {
        var col = new BulkObservableCollection<int>();
        int events = 0;
        col.CollectionChanged += (s, e) => events++;

        col.ReplaceAll([]);

        Assert.Equal(0, events);
    }

    [Fact]
    public void ReplaceAll_DeferredQueryOverSelf_Succeeds()
    {
        var col = new BulkObservableCollection<int> { 3, 1, 2 };

        col.ReplaceAll(col.OrderBy(static x => x));

        Assert.Equal([1, 2, 3], col);
    }
}
