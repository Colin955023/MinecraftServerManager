using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ConsoleCommandHistoryTests
{
    [Fact]
    public void Navigate_EmptyHistory_ReturnsNull()
    {
        var history = new ConsoleCommandHistory(10);

        Assert.Null(history.Navigate(previous: true, "draft"));
        Assert.Null(history.Navigate(previous: false, "draft"));
    }

    [Fact]
    public void Navigate_PreviousThenNext_WalksHistoryAndRestoresDraft()
    {
        var history = new ConsoleCommandHistory(10);
        history.Add("list");
        history.Add("say hi");

        Assert.Equal("say hi", history.Navigate(previous: true, "draft"));
        Assert.Equal("list", history.Navigate(previous: true, "say hi"));
        Assert.Equal("list", history.Navigate(previous: true, "list"));
        Assert.Equal("say hi", history.Navigate(previous: false, "list"));
        Assert.Equal("draft", history.Navigate(previous: false, "say hi"));
        Assert.Equal("draft", history.Navigate(previous: false, "draft"));
    }

    [Fact]
    public void Add_ConsecutiveDuplicate_StoresOnce()
    {
        var history = new ConsoleCommandHistory(10);
        history.Add("list");
        history.Add("list");

        Assert.Equal("list", history.Navigate(previous: true, string.Empty));
        Assert.Equal("list", history.Navigate(previous: true, "list"));
        Assert.Equal(string.Empty, history.Navigate(previous: false, "list"));
    }

    [Fact]
    public void Add_OverCapacity_DropsOldest()
    {
        var history = new ConsoleCommandHistory(2);
        history.Add("a");
        history.Add("b");
        history.Add("c");

        Assert.Equal("c", history.Navigate(previous: true, string.Empty));
        Assert.Equal("b", history.Navigate(previous: true, "c"));
        Assert.Equal("b", history.Navigate(previous: true, "b"));
    }

    [Fact]
    public void Add_AfterNavigating_ResetsPositionAndClearsDraft()
    {
        var history = new ConsoleCommandHistory(10);
        history.Add("a");
        Assert.Equal("a", history.Navigate(previous: true, "draft"));

        history.Add("b");

        Assert.Equal("b", history.Navigate(previous: true, string.Empty));
        Assert.Equal(string.Empty, history.Navigate(previous: false, "b"));
    }
}
