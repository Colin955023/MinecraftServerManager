using System.Collections.ObjectModel;
using System.ComponentModel;
using MinecraftServerManager.App.Controls;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class TableSortTargetTests
{
    private sealed record Row(string Name);

    private static readonly SortKeyMap<Row> Keys = new(("Name", static r => r.Name));

    [Fact]
    public void Attach_AfterDetach_ResortsOnAdd()
    {
        var items = new ObservableCollection<Row> { new("b"), new("a") };
        var pending = new Queue<Action>();
        var target = new TableSortTarget<Row>(() => items, Keys, action => Schedule(pending, action));

        target.Sort("Name", ListSortDirection.Ascending);
        target.Detach();
        target.Attach();

        items.Add(new Row("0"));
        DrainAll(pending);

        Assert.Equal(new[] { "0", "a", "b" }, items.Select(r => r.Name).ToArray());
    }

    [Fact]
    public void Detach_ThenAdd_DoesNotScheduleResort()
    {
        var items = new ObservableCollection<Row> { new("b"), new("a") };
        var pending = new Queue<Action>();
        var target = new TableSortTarget<Row>(() => items, Keys, action => Schedule(pending, action));

        target.Sort("Name", ListSortDirection.Ascending);
        target.Detach();

        items.Add(new Row("0"));

        Assert.Empty(pending);
        Assert.Equal(new[] { "a", "b", "0" }, items.Select(r => r.Name).ToArray());
    }

    [Fact]
    public void Attach_WithoutSort_DoesNotSubscribeOrSort()
    {
        var items = new ObservableCollection<Row> { new("b"), new("a") };
        var pending = new Queue<Action>();
        var target = new TableSortTarget<Row>(() => items, Keys, action => Schedule(pending, action));

        target.Attach();
        items.Add(new Row("0"));

        Assert.Empty(pending);
        Assert.Equal(new[] { "b", "a", "0" }, items.Select(r => r.Name).ToArray());
    }

    private static bool Schedule(Queue<Action> pending, Action action)
    {
        pending.Enqueue(action);
        return true;
    }

    private static void DrainAll(Queue<Action> pending)
    {
        while (pending.Count > 0)
        {
            pending.Dequeue()();
        }
    }
}
