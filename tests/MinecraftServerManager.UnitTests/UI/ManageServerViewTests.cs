using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 表頭自動欄寬估算與欄位顯示文字對照測試
/// </summary>
public sealed class ManageServerViewTests
{
    [Theory]
    [InlineData("01234567890123456789", 202.0)]
    [InlineData("0123456789", 117.0)]
    [InlineData("測試伺服器名稱說明文字", 197.0)]
    public void CalculateAutoFitWidth_EstimatesWidestItem(string value, double expected) =>
        Assert.Equal(expected, SortableTableHeader.CalculateAutoFitWidth(100.0, [value]));

    [Fact]
    public void CalculateAutoFitWidth_WithEmptyOrNullValues_KeepsDefaultWidth() =>
        Assert.Equal(100.0, SortableTableHeader.CalculateAutoFitWidth(100.0, [null, string.Empty, "   "]));

    [Fact]
    public void CalculateAutoFitWidth_WhenWidthExceedsMaxCap_ClampsToMaxColumnWidth() =>
        Assert.Equal(SortableTableHeader.DefaultMaxColumnWidth, SortableTableHeader.CalculateAutoFitWidth(100.0, [new string('伺', 100)]));

    [Fact]
    public void GetDisplayTexts_PrefersDisplayOverrideThenStringSortKey()
    {
        ServerRowItem[] rows = [new() { Name = "Alpha", Size = "1.5 GB", RawSizeBytes = 1_500_000_000 }];

        Assert.Equal(["1.5 GB"], TableSortKeys.Servers.GetDisplayTexts(rows, "Size"));
        Assert.Equal(["Alpha"], TableSortKeys.Servers.GetDisplayTexts(rows, "Name"));
        Assert.Empty(TableSortKeys.Servers.GetDisplayTexts(rows, "Unknown"));
    }
}
