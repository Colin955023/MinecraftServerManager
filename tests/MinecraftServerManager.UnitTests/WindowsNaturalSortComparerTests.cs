using System.ComponentModel;
using MinecraftServerManager.App.Behaviors;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class WindowsNaturalSortComparerTests
{
    private sealed class NamedItem
    {
        public string Name { get; init; } = string.Empty;
    }

    [Fact]
    public void NaturalSortOrdersStringWithNumbersNaturally()
    {
        var items = new List<NamedItem>
        {
            new() { Name = "file10.txt" },
            new() { Name = "file2.txt" },
            new() { Name = "file1.txt" },
            new() { Name = "file20.txt" }
        };

        var comparer = new WindowsNaturalSortComparer("Name", ListSortDirection.Ascending);
        items.Sort(comparer.Compare);

        Assert.Equal("file1.txt", items[0].Name);
        Assert.Equal("file2.txt", items[1].Name);
        Assert.Equal("file10.txt", items[2].Name);
        Assert.Equal("file20.txt", items[3].Name);
    }

    [Fact]
    public void NaturalSortOrdersFileSizeByRawFileSize()
    {
        var items = new List<LocalModRowItem>
        {
            new() { FileName = "b.jar", FileSize = "1.5 MB", RawFileSize = 1_500_000 },
            new() { FileName = "a.jar", FileSize = "200 KB", RawFileSize = 200_000 },
            new() { FileName = "c.jar", FileSize = "10 MB", RawFileSize = 10_000_000 }
        };

        var comparer = new WindowsNaturalSortComparer("FileSize", ListSortDirection.Ascending);
        items.Sort(comparer.Compare);

        Assert.Equal("a.jar", items[0].FileName);
        Assert.Equal("b.jar", items[1].FileName);
        Assert.Equal("c.jar", items[2].FileName);
    }

    [Fact]
    public void NaturalSortOrdersDownloadsByRawCount()
    {
        var items = new List<OnlineModRowItem>
        {
            new() { Title = "Mod B", Downloads = "2,000", DownloadCountRaw = 2000 },
            new() { Title = "Mod A", Downloads = "500", DownloadCountRaw = 500 },
            new() { Title = "Mod C", Downloads = "15,000", DownloadCountRaw = 15000 }
        };

        var comparer = new WindowsNaturalSortComparer("Downloads", ListSortDirection.Ascending);
        items.Sort(comparer.Compare);

        Assert.Equal("Mod A", items[0].Title);
        Assert.Equal("Mod B", items[1].Title);
        Assert.Equal("Mod C", items[2].Title);
    }
}
